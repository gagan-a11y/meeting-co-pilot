
"""
Streaming transcription manager.
Orchestrates: Audio → VAD → Rolling Buffer → Groq API → Partial/Final transcripts

QUALITY IMPROVEMENTS (Phase 3):
- Better deduplication with sentence hashing
- Silero VAD for accurate speech detection (with SimpleVAD fallback)
- Reduced overlap (1.5s instead of 3s)
- Sentence boundary detection
- Debounced final emissions
"""

import asyncio
import numpy as np
import logging
import time
import hashlib
from typing import Optional, Callable, Set
from concurrent.futures import ThreadPoolExecutor
from groq_client import GroqTranscriptionClient
from rolling_buffer import RollingAudioBuffer

# Try to import Silero VAD, fallback to SimpleVAD
try:
    from vad import SileroVAD
    USE_SILERO = True
except ImportError:
    from vad import SimpleVAD
    USE_SILERO = False

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
        
        # Use Silero VAD if available (ML-based, more accurate)
        if USE_SILERO:
            try:
                self.vad = SileroVAD(threshold=0.5)
                logger.info("✅ Using SileroVAD (ML-based)")
            except Exception as e:
                logger.warning(f"⚠️ SileroVAD failed to load: {e}. Using SimpleVAD.")
                from vad import SimpleVAD
                self.vad = SimpleVAD(threshold=0.08)
        else:
            from vad import SimpleVAD
            self.vad = SimpleVAD(threshold=0.08)
            logger.info("ℹ️ Using SimpleVAD (torch not available)")
        
        # IMPROVED: Reduced overlap for less duplication
        # 12s window, 10.5s slide = 1.5s overlap (was 3s)
        self.buffer = RollingAudioBuffer(
            window_duration_ms=12000,  # 12s window
            slide_duration_ms=10500    # 1.5s overlap for context
        )

        # Transcript state
        self.last_partial_text = ""
        self.last_final_text = ""
        self.silence_duration_ms = 0
        self.same_text_count = 0
        self.is_speaking = False
        
        # IMPROVED: Track finalized sentence hashes to prevent duplicates
        self.finalized_hashes: Set[str] = set()
        self.finalized_words: Set[str] = set()  # Track individual words for overlap detection

        # Thread pool for Groq API calls (blocking)
        self.executor = ThreadPoolExecutor(max_workers=2)

        # Performance metrics
        self.total_chunks_processed = 0
        self.total_transcriptions = 0

        # SMART TIMER CONFIG
        self.last_transcription_time = 0
        self.speech_start_time = 0  # When current speech segment started
        
        # Smart trigger thresholds
        self.silence_threshold_ms = 1200   # 1.2s silence → finalize (reverted from 600ms for cleaner output)
        self.max_buffer_duration_ms = 12000  # 12s max → force finalize
        self.punctuation_min_duration_ms = 3000  # Punctuation + 3s → finalize
        self.min_transcription_interval = 2.0  # Min 2s between transcriptions

        logger.info("✅ StreamingTranscriptionManager initialized (SMART TIMER: 1.2s silence, 12s max, punctuation+3s)")


    async def process_audio_chunk(
        self,
        audio_data: bytes,
        on_partial: Optional[Callable] = None,
        on_final: Optional[Callable] = None,
        on_error: Optional[Callable] = None
    ):
        """
        Process incoming audio chunk.

        Args:
            audio_data: Raw PCM audio bytes (16kHz, mono, 16-bit)
            on_partial: Callback for partial transcripts
            on_final: Callback for final transcripts
            on_error: Callback for error messages
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
                self.speech_start_time = time.time()  # Track when speech segment started

            self.silence_duration_ms = 0

            # Add to rolling buffer
            should_transcribe = self.buffer.add_samples(audio_samples)

            # Get current state
            buffer_duration = self.buffer.get_buffer_duration_ms()
            is_full = self.buffer.is_buffer_full()
            current_time = time.time()
            time_since_last = current_time - self.last_transcription_time

            if self.total_chunks_processed % 20 == 0:
                logger.debug(
                    f"📊 Buffer: {buffer_duration:.0f}ms, full={is_full}, "
                    f"since_last={time_since_last:.1f}s"
                )

            # Trigger transcription when buffer is full AND enough time has passed
            if is_full and time_since_last >= self.min_transcription_interval:
                logger.info(f"🚀 Transcription triggered (buffer={buffer_duration:.0f}ms)")

                # Get window and transcribe
                window_bytes = self.buffer.get_window_bytes()
                self.last_transcription_time = current_time

                # Transcribe with Groq (run in thread pool since it's blocking)
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    self.groq.transcribe_audio_sync,
                    window_bytes,
                    "auto",  # Auto-detect language
                    self.last_final_text[-100:] if self.last_final_text else None,
                    True  # translate_to_english=True
                )

                if result.get("error") == "rate_limit_exceeded":
                    logger.warning("⚠️ Groq Rate Limit Exceeded")
                    if on_error:
                        await on_error("Groq API Rate Limit Reached. Please wait a moment or check your plan.")
                elif result["text"]:
                    self.total_transcriptions += 1
                    await self._handle_transcript(
                        text=result["text"],
                        confidence=result.get("confidence", 1.0),
                        on_partial=on_partial,
                        on_final=on_final,
                        metadata=result
                    )

        else:
            # Silence detected
            if self.is_speaking:
                self.silence_duration_ms += 100  # Estimate chunk duration

                # SMART TRIGGER: Finalize if silence > 600ms (configurable)
                if self.silence_duration_ms > self.silence_threshold_ms and self.last_partial_text:
                    # Hash-based deduplication check
                    sentence_hash = self._get_sentence_hash(self.last_partial_text)
                    
                    if sentence_hash not in self.finalized_hashes:
                        logger.info(f"🔇 SMART TRIGGER: Silence ({self.silence_duration_ms}ms > {self.silence_threshold_ms}ms)")

                        if on_final:
                            await on_final({
                                "text": self.last_partial_text,
                                "confidence": 1.0,
                                "reason": "silence"
                            })

                        self.finalized_hashes.add(sentence_hash)
                        self.last_final_text += " " + self.last_partial_text
                    else:
                        logger.debug(f"⏭️  Skipping duplicate (silence): '{self.last_partial_text[:50]}...'")

                    self.last_partial_text = ""
                    self.same_text_count = 0
                    self.is_speaking = False
                    self.speech_start_time = 0  # Reset speech timer

        self.total_chunks_processed += 1

        processing_time = time.time() - start_time
        if processing_time > 0.1:  # Log if taking >100ms
            logger.debug(f"⏱️  Chunk processing: {processing_time*1000:.1f}ms")

    def _word_similarity(self, words1: list, words2: list) -> float:
        """Calculate similarity between two word lists (0.0 to 1.0)."""
        if not words1 or not words2:
            return 0.0
        # Count matching words
        set1 = set(w.lower() for w in words1)
        set2 = set(w.lower() for w in words2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0

    def _remove_overlap(self, new_text: str) -> str:
        """
        Remove overlapping text using fuzzy matching.
        Handles Whisper's slight wording variations in overlapping audio.

        Uses word-level similarity to detect overlaps even when exact text differs.
        """
        if not self.last_final_text:
            return new_text

        final_words = self.last_final_text.split()
        new_words = new_text.split()

        if len(new_words) < 4:
            return new_text

        # Look for overlaps in the first 40% of new text (overlap window)
        max_overlap_check = min(20, len(new_words) // 2 + 5)
        
        # Get last 30 words of previous transcript for comparison
        search_window = min(50, len(final_words))  # Increased from 30 to catch more context
        final_tail_words = final_words[-search_window:]
        
        best_overlap = 0
        similarity_threshold = 0.5  # Lowered from 0.6 to catch more overlaps
        
        # Try different overlap sizes, largest first
        for overlap_size in range(max_overlap_check, 2, -1):
            new_head = new_words[:overlap_size]
            
            # Check similarity against different positions in final tail
            for start in range(0, min(15, search_window)):
                if start + overlap_size > search_window:
                    break
                    
                final_segment = final_tail_words[start:start + overlap_size]
                similarity = self._word_similarity(new_head, final_segment)
                
                if similarity >= similarity_threshold:
                    best_overlap = max(best_overlap, overlap_size)
                    break
            
            # Also check if new_head matches the END of final_tail
            if overlap_size <= search_window:
                final_end = final_tail_words[-overlap_size:]
                similarity = self._word_similarity(new_head, final_end)
                if similarity >= similarity_threshold:
                    best_overlap = max(best_overlap, overlap_size)
            
            if best_overlap > 0:
                break

        # Remove overlapping words
        if best_overlap > 0:
            deduplicated = " ".join(new_words[best_overlap:])
            logger.info(f"🔄 Removed ~{best_overlap} overlapping words (fuzzy match)")
            return deduplicated.strip()

        return new_text

    def _get_sentence_hash(self, text: str) -> str:
        """Generate hash for normalized text to detect exact duplicates."""
        # Normalize: lowercase, collapse whitespace
        normalized = ' '.join(text.lower().split())
        return hashlib.md5(normalized.encode()).hexdigest()[:16]
    
    def _is_complete_sentence(self, text: str) -> bool:
        """Check if text ends with sentence-ending punctuation."""
        text = text.strip()
        # Check for common sentence endings in English/Hindi
        sentence_endings = ('.', '!', '?', '。', '？', '！', '।')
        return text.endswith(sentence_endings)
    
    def _extract_new_words(self, text: str) -> str:
        """Remove words already seen in finalized transcripts."""
        words = text.split()
        new_words = []
        for word in words:
            word_lower = word.lower().strip('.,!?;:')
            if word_lower and word_lower not in self.finalized_words:
                new_words.append(word)
                self.finalized_words.add(word_lower)
        return ' '.join(new_words)
    
    def _get_ngrams(self, text: str, n: int = 4) -> set:
        """Get n-grams (word sequences) from text for similarity matching."""
        words = text.lower().split()
        if len(words) < n:
            return {' '.join(words)} if words else set()
        return {' '.join(words[i:i+n]) for i in range(len(words) - n + 1)}
    
    def _is_near_duplicate(self, text: str, threshold: float = 0.5) -> bool:
        """Check if text is a near-duplicate of already finalized content.
        
        Uses n-gram matching to catch phrases like 'we can jump on the call'
        that appear in both old and new text even if exact hash differs.
        """
        if not self.last_final_text or len(text.split()) < 5:
            return False
        
        # Get 3-grams from new text (changed from 4 for finer detection)
        new_ngrams = self._get_ngrams(text, n=3)
        if not new_ngrams:
            return False
        
        # Get 3-grams from last portion of finalized text
        final_words = self.last_final_text.split()
        # Only check last ~100 words for performance
        recent_final = ' '.join(final_words[-100:]) if len(final_words) > 100 else self.last_final_text
        final_ngrams = self._get_ngrams(recent_final, n=3)
        
        if not final_ngrams:
            return False
        
        # Calculate overlap ratio
        overlap = len(new_ngrams & final_ngrams)
        overlap_ratio = overlap / len(new_ngrams)
        
        if overlap_ratio >= threshold:
            logger.debug(f"⏭️  Near-duplicate detected ({overlap_ratio:.0%} overlap): '{text[:50]}...'")
            return True
        
        return False

    async def _handle_transcript(
        self,
        text: str,
        confidence: float,
        on_partial: Optional[Callable],
        on_final: Optional[Callable],
        metadata: Optional[dict] = None
    ):
        """Handle partial vs final transcript logic with improved deduplication.
        
        QUALITY IMPROVEMENTS:
        - Hash-based duplicate detection
        - Sentence boundary detection
        - Debounced final emissions
        """

        # Skip empty or very short text
        if not text or len(text.strip()) < 3:
            return

        # IMPROVED: Remove overlapping words from start
        deduplicated_text = self._remove_overlap(text)

        # Skip if nothing left after deduplication
        if not deduplicated_text or len(deduplicated_text.strip()) < 3:
            logger.debug(f"⏭️  Skipped - fully overlapping: '{text[:50]}...'")
            return

        # Use deduplicated text for processing
        text = deduplicated_text
        
        # IMPROVED: Check if this exact text was already finalized (hash check)
        sentence_hash = self._get_sentence_hash(text)
        if sentence_hash in self.finalized_hashes:
            logger.debug(f"⏭️  Skipping duplicate hash: '{text[:50]}...'")
            return
        
        # IMPROVED: Check for near-duplicates using n-gram matching
        if self._is_near_duplicate(text, threshold=0.35):  # Lowered from 0.4 to catch more
            # 40% of 4-grams match = likely duplicate
            return

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
                "is_stable": self.same_text_count >= 2
            })

        # SMART TIMER TRIGGER LOGIC
        is_complete_sentence = self._is_complete_sentence(text)
        
        # Calculate speech duration
        speech_duration_ms = (time.time() - self.speech_start_time) * 1000 if self.speech_start_time > 0 else 0
        
        # Determine trigger reason
        trigger_reason = None
        
        # Trigger 1: Punctuation + 3s buffer
        if is_complete_sentence and speech_duration_ms >= self.punctuation_min_duration_ms:
            trigger_reason = "punctuation"
            logger.info(f"⏱️ SMART TRIGGER: Punctuation + {speech_duration_ms:.0f}ms speech")
        
        # Trigger 2: Max buffer timeout (12s)
        elif speech_duration_ms >= self.max_buffer_duration_ms:
            trigger_reason = "timeout"
            logger.info(f"⏱️ SMART TRIGGER: Max timeout ({speech_duration_ms:.0f}ms >= {self.max_buffer_duration_ms}ms)")
        
        # Trigger 3: Stability (text unchanged 4+ times)
        elif self.same_text_count >= 4:
            trigger_reason = "stability"
            logger.info(f"⏱️ SMART TRIGGER: Text stable ({self.same_text_count} repeats)")
        
        # Trigger 4: Complete sentence + stable (2+ repeats)
        elif self.same_text_count >= 2 and is_complete_sentence:
            trigger_reason = "sentence_complete"
            logger.info(f"⏱️ SMART TRIGGER: Sentence complete + stable")

        if trigger_reason:
            # Debounce - check hash before emitting
            if sentence_hash in self.finalized_hashes:
                logger.debug(f"⏭️  Debounced duplicate final: '{text[:50]}...'")
                return
                
            if on_final:
                logger.debug(f"✅ Finalizing: '{text[:50]}...' (reason={trigger_reason})")

                final_data = {
                    "text": text,
                    "confidence": confidence,
                    "reason": trigger_reason
                }

                # Include translation metadata if available
                if metadata:
                    if metadata.get("original_text"):
                        final_data["original_text"] = metadata["original_text"]
                    if metadata.get("translated"):
                        final_data["translated"] = metadata["translated"]

                await on_final(final_data)

                # Track finalized text
                self.finalized_hashes.add(sentence_hash)
                self.last_final_text += " " + text
                self.last_partial_text = ""
                self.same_text_count = 0
                self.speech_start_time = time.time()  # Reset for next segment

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
        # Clear deduplication tracking
        self.finalized_hashes.clear()
        self.finalized_words.clear()
        logger.info("🔄 Manager reset")

    def cleanup(self):
        """Cleanup resources"""
        self.executor.shutdown(wait=False)
        logger.info("🧹 Manager cleanup complete")
