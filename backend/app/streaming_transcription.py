
"""
Streaming transcription manager.
Orchestrates: Audio → VAD → Rolling Buffer → Groq API → Partial/Final transcripts
"""

import asyncio
import numpy as np
import logging
import time
from typing import Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from groq_client import GroqTranscriptionClient
from vad import SimpleVAD
from rolling_buffer import RollingAudioBuffer

logger = logging.getLogger(__name__)

class StreamingTranscriptionManager:
    """
    Orchestrates real-time transcription pipeline:
    Audio → VAD → Rolling Buffer → Groq API → Partial/Final
    """

    def __init__(self, groq_api_key: str):
        """
        Args:
            groq_api_key: Groq API key for Whisper Large v3
        """
        self.groq = GroqTranscriptionClient(groq_api_key)
        self.vad = SimpleVAD(threshold=0.08)  # Even less sensitive (was 0.05)
        self.buffer = RollingAudioBuffer(
            window_duration_ms=6000,  # 6s window - more context for Hinglish sentences
            slide_duration_ms=5000    # Process every 5s - 1s overlap (catches boundary words)
        )

        # Transcript state
        self.last_partial_text = ""
        self.last_final_text = ""
        self.silence_duration_ms = 0
        self.same_text_count = 0
        self.is_speaking = False

        # Thread pool for Groq API calls (blocking)
        self.executor = ThreadPoolExecutor(max_workers=2)

        # Performance metrics
        self.total_chunks_processed = 0
        self.total_transcriptions = 0

        logger.info("✅ StreamingTranscriptionManager initialized")

    async def process_audio_chunk(
        self,
        audio_data: bytes,
        on_partial: Optional[Callable] = None,
        on_final: Optional[Callable] = None
    ):
        """
        Process incoming audio chunk.

        Args:
            audio_data: Raw PCM audio bytes (16kHz, mono, 16-bit)
            on_partial: Callback for partial transcripts
            on_final: Callback for final transcripts
        """
        start_time = time.time()

        # Convert bytes to numpy array
        audio_samples = np.frombuffer(audio_data, dtype=np.int16)

        # Check for speech
        is_speech = self.vad.is_speech(audio_samples)

        if is_speech:
            if not self.is_speaking:
                logger.debug("🎤 Speech started")
                self.is_speaking = True

            self.silence_duration_ms = 0

            # Add to rolling buffer
            should_transcribe = self.buffer.add_samples(audio_samples)

            if should_transcribe and self.buffer.is_buffer_full():
                # Get 2-second window
                window_bytes = self.buffer.get_window_bytes()

                # Transcribe with Groq (run in thread pool since it's blocking)
                # Auto-detect language, then translate if needed
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    self.groq.transcribe_audio_sync,
                    window_bytes,
                    "auto",  # Auto-detect language (not forcing Hindi)
                    self.last_final_text[-100:] if self.last_final_text else None,
                    True  # translate_to_english=True
                )

                if result["text"]:
                    self.total_transcriptions += 1
                    await self._handle_transcript(
                        text=result["text"],
                        confidence=result.get("confidence", 1.0),
                        on_partial=on_partial,
                        on_final=on_final,
                        metadata=result  # Pass full result for translation data
                    )

        else:
            # Silence detected
            if self.is_speaking:
                self.silence_duration_ms += 100  # Estimate chunk duration

                # Finalize if silence > 1000ms (was 500ms)
                if self.silence_duration_ms > 1000 and self.last_partial_text:
                    # Deduplication check
                    if self.last_partial_text not in self.last_final_text:
                        logger.debug(f"🔇 Speech ended (silence > 1s)")

                        if on_final:
                            await on_final({
                                "text": self.last_partial_text,
                                "confidence": 1.0,
                                "reason": "silence"
                            })

                        self.last_final_text += " " + self.last_partial_text
                    else:
                        logger.debug(f"⏭️  Skipping duplicate (silence): '{self.last_partial_text[:50]}...'")

                    self.last_partial_text = ""
                    self.same_text_count = 0
                    self.is_speaking = False

        self.total_chunks_processed += 1

        processing_time = time.time() - start_time
        if processing_time > 0.1:  # Log if taking >100ms
            logger.debug(f"⏱️  Chunk processing: {processing_time*1000:.1f}ms")

    def _remove_overlap(self, new_text: str) -> str:
        """
        Remove overlapping text from new transcript using smart word matching.

        Example:
            last_final_text = "Hello how are you"
            new_text = "are you doing today"
            return = "doing today"  (removed "are you" overlap)
        """
        if not self.last_final_text:
            return new_text

        # Get last N words from final transcript to check for overlap
        final_words = self.last_final_text.split()
        new_words = new_text.split()

        # Don't process if too short
        if len(new_words) < 2:
            return new_text

        # Check for overlapping words at the start of new text
        # Look for matches in last 10 words of final transcript
        overlap_length = 0
        search_window = min(10, len(final_words))

        for i in range(search_window, 0, -1):
            # Get last i words from final transcript
            final_tail = " ".join(final_words[-i:]).lower()

            # Check if new text starts with these words
            for j in range(1, min(i + 1, len(new_words) + 1)):
                new_head = " ".join(new_words[:j]).lower()

                # Found overlap
                if final_tail.endswith(new_head) or new_head in final_tail:
                    overlap_length = max(overlap_length, j)

        # Remove overlapping words from start of new text
        if overlap_length > 0:
            deduplicated = " ".join(new_words[overlap_length:])
            logger.debug(f"🔄 Removed {overlap_length} overlapping words: '{' '.join(new_words[:overlap_length])}'")
            return deduplicated.strip()

        return new_text

    async def _handle_transcript(
        self,
        text: str,
        confidence: float,
        on_partial: Optional[Callable],
        on_final: Optional[Callable],
        metadata: Optional[dict] = None
    ):
        """Handle partial vs final transcript logic with smart deduplication"""

        # Skip empty or very short text
        if not text or len(text.strip()) < 3:
            return

        # SMART DEDUPLICATION: Remove overlapping words from start
        deduplicated_text = self._remove_overlap(text)

        # Skip if nothing left after deduplication
        if not deduplicated_text or len(deduplicated_text.strip()) < 3:
            logger.debug(f"⏭️  Skipped - fully overlapping: '{text[:50]}...'")
            return

        # Use deduplicated text for processing
        text = deduplicated_text

        # Check if text stabilized
        if text == self.last_partial_text:
            self.same_text_count += 1
        else:
            self.same_text_count = 0
            self.last_partial_text = text

        # Emit partial
        if on_partial:
            await on_partial({
                "text": text,
                "confidence": confidence,
                "is_stable": self.same_text_count >= 2  # Reduced from 3 for faster finalization
            })

        # Check if should finalize
        should_finalize = (
            self.same_text_count >= 2 or  # Text stable (appeared 3 times)
            confidence > 0.95              # High confidence
        )

        if should_finalize:
            if on_final:
                logger.debug(f"✅ Finalizing: '{text[:50]}...'")

                final_data = {
                    "text": text,
                    "confidence": confidence,
                    "reason": "stability"
                }

                # Include translation metadata if available
                if metadata:
                    if metadata.get("original_text"):
                        final_data["original_text"] = metadata["original_text"]
                    if metadata.get("translated"):
                        final_data["translated"] = metadata["translated"]

                await on_final(final_data)

                self.last_final_text += " " + text
                self.last_partial_text = ""
                self.same_text_count = 0

    def get_stats(self) -> dict:
        """Get performance statistics"""
        return {
            "chunks_processed": self.total_chunks_processed,
            "transcriptions": self.total_transcriptions,
            "buffer_duration_ms": self.buffer.get_buffer_duration_ms(),
            "is_speaking": self.is_speaking,
            "final_text_length": len(self.last_final_text),
            "partial_text": self.last_partial_text
        }

    def reset(self):
        """Reset manager state for new recording"""
        self.buffer.clear()
        self.last_partial_text = ""
        self.last_final_text = ""
        self.silence_duration_ms = 0
        self.same_text_count = 0
        self.is_speaking = False
        self.total_chunks_processed = 0
        self.total_transcriptions = 0
        logger.info("🔄 Manager reset")

    def cleanup(self):
        """Cleanup resources"""
        self.executor.shutdown(wait=False)
        logger.info("🧹 Manager cleanup complete")
