"""
Speaker Diarization Service.

This module handles post-meeting speaker diarization using cloud APIs
(Deepgram or AssemblyAI). It processes recorded audio to identify
"who spoke when" and aligns the results with existing transcripts.

Features:
- Cloud API integration (Deepgram Nova-2, AssemblyAI)
- Audio chunk merging and conversion
- Transcript-speaker alignment
- Speaker segment generation
"""

import asyncio
import httpx
import logging
import os
import json
import aiofiles
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from dataclasses import dataclass

try:
    from .recorder import AudioRecorder
    from .groq_client import GroqTranscriptionClient
    from .alignment import AlignmentEngine
except (ImportError, ValueError):
    from services.audio.recorder import AudioRecorder
    from services.audio.groq_client import GroqTranscriptionClient
    from services.audio.alignment import AlignmentEngine

logger = logging.getLogger(__name__)


@dataclass
class SpeakerSegment:
    """Represents a speaker segment with timing and text."""

    speaker: str
    start_time: float
    end_time: float
    text: str
    confidence: float = 1.0
    word_count: int = 0


@dataclass
class DiarizationResult:
    """Result of diarization processing."""

    status: str  # 'completed', 'failed', 'pending'
    meeting_id: str
    speaker_count: int
    segments: List[SpeakerSegment]
    processing_time_seconds: float
    provider: str
    error: Optional[str] = None


class DiarizationService:
    """
    Service for speaker diarization using cloud APIs.

    Supported providers:
    - Deepgram (Nova-2): Fast, good accuracy, $0.25/hour
    - AssemblyAI: Best in noisy conditions, $0.37/hour
    """

    def __init__(self, provider: str = "deepgram", groq_api_key: str = None):
        """
        Initialize the diarization service.

        Args:
            provider: 'deepgram' or 'assemblyai'
        """
        self.provider = provider.lower()

        # Load API keys from environment
        self.deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
        self.assemblyai_api_key = os.getenv("ASSEMBLYAI_API_KEY")

        # Groq client for high-fidelity transcription
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.groq = (
            GroqTranscriptionClient(self.groq_api_key) if self.groq_api_key else None
        )

        # API endpoints
        self.deepgram_url = "https://api.deepgram.com/v1/listen"
        self.assemblyai_url = "https://api.assemblyai.com/v2"

        # Feature flag
        self.enabled = os.getenv("ENABLE_DIARIZATION", "true").lower() == "true"

        # Alignment engine (3-tier logic)
        self.alignment_engine = AlignmentEngine()

        logger.info(
            f"DiarizationService initialized (provider={provider}, enabled={self.enabled})"
        )

    async def transcribe_with_whisper(self, audio_data: bytes) -> List[Dict]:
        """
        Run high-fidelity Whisper transcription on the full meeting audio.
        Returns segments for alignment.
        """
        if not self.groq:
            logger.error("No Groq API key provided for high-fidelity transcription")
            return []

        logger.info("💎 Running Gold Standard Whisper transcription...")
        result = await self.groq.transcribe_full_audio(audio_data)

        if result.get("error"):
            logger.error(f"Gold transcription failed: {result['error']}")
            return []

        logger.info(
            f"✅ Gold transcription complete: {len(result.get('segments', []))} segments"
        )
        return result.get("segments", [])

    async def _get_api_key(
        self, provider: str = None, user_email: str = None
    ) -> Optional[str]:
        """
        Get API key for the specified provider.
        Priority: 1) User-specific key from DB, 2) Environment variable
        """
        provider = provider or self.provider

        # Try environment variable first (fastest)
        env_key = None
        if provider == "deepgram":
            env_key = os.getenv("DEEPGRAM_API_KEY")
        elif provider == "assemblyai":
            env_key = os.getenv("ASSEMBLYAI_API_KEY")

        if env_key:
            return env_key

        # Fall back to database lookup if user_email provided
        if user_email:
            try:
                from ..db import DatabaseManager

                db = DatabaseManager()
                db_key = await db.get_api_key(provider, user_email=user_email)
                if db_key:
                    return db_key
            except Exception as e:
                logger.warning(f"Failed to get API key from database: {e}")

        # Return cached instance variable as final fallback
        if provider == "deepgram":
            return self.deepgram_api_key
        elif provider == "assemblyai":
            return self.assemblyai_api_key

        logger.error(f"No API key found for provider: {provider}")
        return None

    async def diarize_meeting(
        self,
        meeting_id: str,
        storage_path: str = "./data/recordings",
        provider: str = None,
        audio_data: bytes = None,
        user_email: str = None,
    ) -> DiarizationResult:
        """
        Run speaker diarization on a meeting's recorded audio.

        This is the main entry point for diarization. It:
        1. Merges audio chunks (or uses provided audio_data)
        2. Sends to cloud API
        3. Processes results
        4. Returns speaker segments

        Args:
            meeting_id: Meeting ID to diarize
            storage_path: Base path for recordings
            provider: Override default provider
            audio_data: Optional pre-loaded audio bytes (PCM or WAV)
            user_email: Optional user email for fetching API keys

        Returns:
            DiarizationResult with speaker segments
        """
        start_time = datetime.utcnow()
        provider = provider or self.provider

        if not self.enabled:
            return DiarizationResult(
                status="disabled",
                meeting_id=meeting_id,
                speaker_count=0,
                segments=[],
                processing_time_seconds=0,
                provider=provider,
                error="Diarization is disabled",
            )

        api_key = await self._get_api_key(provider, user_email)
        if not api_key:
            return DiarizationResult(
                status="failed",
                meeting_id=meeting_id,
                speaker_count=0,
                segments=[],
                processing_time_seconds=0,
                provider=provider,
                error=f"No API key configured for {provider}. Set {provider.upper()}_API_KEY environment variable.",
            )

        try:
            logger.info(
                f"🎯 Starting diarization for meeting {meeting_id} with {provider}"
            )

            # Step 1: Get Audio Data
            if audio_data is None:
                # Try to find existing merged files first (Imported)
                recording_dir = Path(storage_path) / meeting_id
                merged_pcm = recording_dir / "merged_recording.pcm"
                merged_wav = recording_dir / "merged_recording.wav"

                if merged_pcm.exists():
                    logger.info(f"📂 Found existing merged PCM file for {meeting_id}")
                    async with aiofiles.open(merged_pcm, "rb") as f:
                        audio_data = await f.read()
                elif merged_wav.exists():
                    logger.info(f"📂 Found existing merged WAV file for {meeting_id}")
                    async with aiofiles.open(merged_wav, "rb") as f:
                        audio_data = await f.read()
                else:
                    # Fallback to merging chunks
                    logger.info(
                        f"⚠️ Merged audio missing for {meeting_id}, attempting to merge chunks locally..."
                    )
                    audio_data = await AudioRecorder.merge_chunks(
                        meeting_id, storage_path
                    )

            # If still no audio, check for any chunks and try harder
            if not audio_data:
                recording_dir = Path(storage_path) / meeting_id
                if recording_dir.exists():
                    chunks = list(recording_dir.glob("chunk_*.pcm"))
                    if chunks:
                        logger.info(
                            f"⚠️ explicit chunk merge triggered for {len(chunks)} chunks"
                        )
                        audio_data = await AudioRecorder.merge_chunks(
                            meeting_id, storage_path
                        )

            if not audio_data:
                return DiarizationResult(
                    status="failed",
                    meeting_id=meeting_id,
                    speaker_count=0,
                    segments=[],
                    processing_time_seconds=0,
                    provider=provider,
                    error="No audio data found for this meeting. Ensure recording was enabled.",
                )

            # Step 2: Convert to WAV and SAVE for quality auditing
            # Check if it's already WAV (RIFF header)
            is_wav = audio_data.startswith(b"RIFF")

            if is_wav:
                wav_data = audio_data
                logger.info("📦 Audio is already WAV format")
            else:
                wav_data = AudioRecorder.convert_pcm_to_wav(audio_data)
                logger.info("📦 Converted PCM to WAV")

            audio_duration_seconds = len(wav_data) / (
                16000 * 2
            )  # Approx if PCM, not accurate for WAV header but ok for log

            # Persist WAV to disk so user can listen to it (if not already there)
            try:
                wav_path = Path(storage_path) / meeting_id / "merged_recording.wav"
                if not wav_path.exists():
                    with open(wav_path, "wb") as f:
                        f.write(wav_data)
                    logger.info(f"💾 Saved merged WAV for auditing: {wav_path}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to save WAV file (non-critical): {e}")

            logger.info(f"📦 Audio prepared: {len(wav_data)} bytes")

            # Step 3: Send to diarization API
            if provider == "deepgram":
                segments = await self._diarize_with_deepgram(
                    wav_data, meeting_id, api_key
                )
            elif provider == "assemblyai":
                segments = await self._diarize_with_assemblyai(
                    wav_data, meeting_id, api_key
                )
            else:
                raise ValueError(f"Unknown provider: {provider}")

            # Calculate processing time
            processing_time = (datetime.utcnow() - start_time).total_seconds()

            # Count unique speakers
            unique_speakers = set(seg.speaker for seg in segments)

            logger.info(
                f"✅ Diarization complete: {len(segments)} segments, "
                f"{len(unique_speakers)} speakers, "
                f"{processing_time:.1f}s processing time"
            )

            return DiarizationResult(
                status="completed",
                meeting_id=meeting_id,
                speaker_count=len(unique_speakers),
                segments=segments,
                processing_time_seconds=processing_time,
                provider=provider,
            )

        except Exception as e:
            logger.error(f"Diarization failed for meeting {meeting_id}: {e}")
            return DiarizationResult(
                status="failed",
                meeting_id=meeting_id,
                speaker_count=0,
                segments=[],
                processing_time_seconds=(
                    datetime.utcnow() - start_time
                ).total_seconds(),
                provider=provider,
                error=str(e),
            )

    async def _diarize_with_deepgram(
        self, audio_data: bytes, meeting_id: str, api_key: str
    ) -> List[SpeakerSegment]:
        """
        Send audio to Deepgram for diarization.

        Uses Deepgram Nova-2 model with diarization enabled.

        Args:
            audio_data: WAV audio bytes

        Returns:
            List of SpeakerSegment objects
        """
        max_retries = 3
        retry_delay = 1
        last_error = None

        # Determine content type based on header
        content_type = "audio/wav"
        if audio_data.startswith(b"ID3") or audio_data.startswith(b"\xff\xfb"):
            content_type = "audio/mp3"
        elif audio_data.startswith(b"OggS"):
            content_type = "audio/ogg"

        # Helper to create an IPv4-only transport (fixes Docker/network issues)
        def _get_transport_ipv4():
            import httpcore

            return httpx.AsyncHTTPTransport(local_address="0.0.0.0")

        for attempt in range(max_retries):
            try:
                # Use transport explicitly to force IPv4 if needed, or rely on standard client
                async with httpx.AsyncClient(
                    timeout=300.0, transport=_get_transport_ipv4()
                ) as client:
                    response = await client.post(
                        self.deepgram_url,
                        headers={
                            "Authorization": f"Token {api_key}",
                            "Content-Type": content_type,
                        },
                        params={
                            "model": "nova-2",
                            "diarize": "true",
                            "punctuate": "true",
                            "utterances": "true",
                            "smart_format": "false",
                        },
                        content=audio_data,
                    )

                    if response.status_code != 200:
                        error_text = response.text
                        logger.error(
                            f"Deepgram API error (Attempt {attempt + 1}/{max_retries}): {response.status_code} - {error_text}"
                        )
                        # If 4xx error (client error), do not retry
                        if 400 <= response.status_code < 500:
                            raise Exception(
                                f"Deepgram API error: {response.status_code}"
                            )

                        response.raise_for_status()

                    result = response.json()

                    # Parse response into segments
                    segments = []

                    # QUALITY TRANSCRIPTION: Prefer 'utterances' for natural punctuation,
                    # fallback to 'words' reconstruction for 100% completeness.
                    utterances = result.get("results", {}).get("utterances", [])
                    words = (
                        result.get("results", {})
                        .get("channels", [{}])[0]
                        .get("alternatives", [{}])[0]
                        .get("words", [])
                    )

                    if not words and not utterances:
                        logger.warning(
                            f"No results returned by Deepgram for meeting {meeting_id}"
                        )
                        return []

                    raw_segments = []

                    if utterances:
                        # Use punctuated utterances
                        for u in utterances:
                            raw_segments.append(
                                SpeakerSegment(
                                    speaker=f"Speaker {u.get('speaker', 0)}",
                                    start_time=u.get("start", 0),
                                    end_time=u.get("end", 0),
                                    text=u.get("transcript", ""),
                                    confidence=u.get("confidence", 1.0),
                                    word_count=len(u.get("words", [])),
                                )
                            )
                    elif words:
                        # Fallback: Reconstruct from words (raw, but complete)
                        current_speaker = None
                        current_segment = None

                        for w in words:
                            speaker = f"Speaker {w.get('speaker', 0)}"
                            if speaker != current_speaker:
                                if current_segment:
                                    raw_segments.append(current_segment)
                                current_speaker = speaker
                                current_segment = SpeakerSegment(
                                    speaker=speaker,
                                    start_time=w.get("start", 0),
                                    end_time=w.get("end", 0),
                                    text=w.get("word", ""),
                                    confidence=w.get("speaker_confidence", 1.0),
                                    word_count=1,
                                )
                            else:
                                if current_segment:
                                    current_segment.end_time = w.get(
                                        "end", current_segment.end_time
                                    )
                                    current_segment.text += " " + w.get("word", "")
                                    current_segment.word_count += 1
                        if current_segment:
                            raw_segments.append(current_segment)

                    if not raw_segments:
                        logger.warning(f"No usable segments for {meeting_id}")
                        return []

                    # NATURAL GROUPING: Merge consecutive segments from same speaker
                    segments = []
                    current = raw_segments[0]
                    MAX_GAP = 5.0  # seconds

                    for next_seg in raw_segments[1:]:
                        gap = next_seg.start_time - current.end_time
                        if next_seg.speaker == current.speaker and gap < MAX_GAP:
                            # Merge
                            current.text += " " + next_seg.text
                            current.end_time = next_seg.end_time
                            current.word_count += next_seg.word_count
                        else:
                            segments.append(current)
                            current = next_seg

                    segments.append(current)
                    logger.info(
                        f"Reconstructed {len(segments)} natural segments for {meeting_id}"
                    )
                    return segments

            except httpx.NetworkError as e:
                last_error = e
                logger.warning(
                    f"Deepgram network error (Attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (2**attempt))
            except Exception as e:
                # Non-network errors (or 4xx from above) - re-raise immediately
                raise e

        # If we get here, all retries failed
        raise Exception(
            f"Deepgram API failed after {max_retries} attempts: {last_error}"
        )

    async def _diarize_with_assemblyai(
        self, audio_data: bytes, meeting_id: str, api_key: str
    ) -> List[SpeakerSegment]:
        """
        Send audio to AssemblyAI for diarization.

        Uses AssemblyAI's transcription with speaker_labels enabled.
        Note: AssemblyAI uses a two-step process (upload then transcribe).

        Args:
            audio_data: WAV audio bytes

        Returns:
            List of SpeakerSegment objects
        """
        async with httpx.AsyncClient(timeout=600.0) as client:
            # Step 1: Upload audio file
            upload_response = await client.post(
                f"{self.assemblyai_url}/upload",
                headers={
                    "authorization": api_key,
                    "content-type": "application/octet-stream",
                },
                content=audio_data,
            )

            if upload_response.status_code != 200:
                raise Exception(
                    f"AssemblyAI upload failed: {upload_response.status_code}"
                )

            audio_url = upload_response.json().get("upload_url")
            logger.info(f"Audio uploaded to AssemblyAI")

            # Step 2: Request transcription with diarization
            transcript_response = await client.post(
                f"{self.assemblyai_url}/transcript",
                headers={
                    "authorization": api_key,
                    "content-type": "application/json",
                },
                json={
                    "audio_url": audio_url,
                    "speaker_labels": True,
                    "punctuate": True,
                    "format_text": True,
                },
            )

            if transcript_response.status_code != 200:
                raise Exception(
                    f"AssemblyAI transcription request failed: {transcript_response.status_code}"
                )

            transcript_id = transcript_response.json().get("id")
            logger.info(f"Transcription started: {transcript_id}")

            # Step 3: Poll for completion
            while True:
                status_response = await client.get(
                    f"{self.assemblyai_url}/transcript/{transcript_id}",
                    headers={"authorization": api_key},
                )

                status_data = status_response.json()
                status = status_data.get("status")

                if status == "completed":
                    break
                elif status == "error":
                    raise Exception(
                        f"AssemblyAI transcription failed: {status_data.get('error')}"
                    )

                logger.debug(f"AssemblyAI status: {status}")
                await asyncio.sleep(3)  # Poll every 3 seconds

            # Step 4: Parse results
            segments = []
            utterances = status_data.get("utterances", [])

            for utterance in utterances:
                segment = SpeakerSegment(
                    speaker=f"Speaker {utterance.get('speaker', 'A')}",
                    start_time=utterance.get("start", 0)
                    / 1000,  # AssemblyAI uses milliseconds
                    end_time=utterance.get("end", 0) / 1000,
                    text=utterance.get("text", ""),
                    confidence=utterance.get("confidence", 1.0),
                    word_count=len(utterance.get("words", [])),
                )
                segments.append(segment)

            logger.info(f"AssemblyAI returned {len(segments)} speaker segments")
            return segments

    async def align_with_transcripts(
        self,
        meeting_id: str,
        diarization_result: DiarizationResult,
        transcripts: List[Dict],
    ) -> Tuple[List[Dict], Dict]:
        """
        Align diarization results with transcript segments using 3-tier alignment.

        Uses the new AlignmentEngine with:
        - Tier 1: Time overlap (primary)
        - Tier 2: Word density (handles timestamp drift)
        - Tier 3: Explicit UNCERTAIN state

        Returns:
            Tuple of (aligned_transcripts, metrics)
        """
        if diarization_result.status != "completed":
            logger.warning(
                f"Cannot align - diarization status: {diarization_result.status}"
            )
            return transcripts, {
                "error": f"Diarization status: {diarization_result.status}"
            }

        # Convert SpeakerSegment dataclasses to dicts for alignment engine
        speaker_segments = [
            {
                "speaker": seg.speaker,
                "start_time": seg.start_time,
                "end_time": seg.end_time,
                "text": seg.text,
                "confidence": seg.confidence,
            }
            for seg in diarization_result.segments
        ]

        if not speaker_segments:
            logger.warning("No diarization segments found to align with.")
            # Map everything to Unknown if no detection happened
            unknown_transcripts = [
                {
                    **t,
                    "speaker": "Unknown",
                    "text": t.get("text", t.get("transcript", "")),
                    "alignment_state": "UNKNOWN_SPEAKER",
                    "speaker_confidence": 0.0,
                }
                for t in transcripts
            ]
            return unknown_transcripts, {
                "total_segments": len(transcripts),
                "unknown_count": len(transcripts),
                "avg_confidence": 0.0,
            }

        # Use the new AlignmentEngine
        aligned_transcripts, metrics = self.alignment_engine.align_batch(
            transcripts, speaker_segments
        )

        # Assign UUIDs to segments if missing (crucial for React keys and streaming matching)
        import uuid

        for seg in aligned_transcripts:
            if "id" not in seg:
                seg["id"] = str(uuid.uuid4())

        logger.info(
            f"✅ Aligned {meeting_id}: {metrics['confident_count']}/{metrics['total_segments']} confident, "
            f"{metrics['uncertain_count']} uncertain, {metrics['overlap_count']} overlap, "
            f"avg_conf={metrics['avg_confidence']:.2f}"
        )

        return aligned_transcripts, metrics

    def format_transcript_with_speakers(self, transcripts: List[Dict]) -> str:
        """
        Format transcripts with speaker labels for LLM consumption.

        Args:
            transcripts: List of transcript dicts with 'speaker' and 'text' fields

        Returns:
            Formatted string with speaker labels
        """
        lines = []
        current_speaker = None

        for t in transcripts:
            speaker = t.get("speaker", "Unknown")
            text = t.get("text", "").strip()

            # CLEANUP: Remove 'undefined' prefix if present
            if text.startswith("undefined "):
                text = text[10:]  # Remove 'undefined '

            if not text:
                continue

            # Group consecutive segments from same speaker
            if speaker != current_speaker:
                lines.append(f"\n**{speaker}:** {text}")
                current_speaker = speaker
            else:
                lines.append(f" {text}")

        return "".join(lines).strip()


# Singleton instance
_diarization_service: Optional[DiarizationService] = None


def get_diarization_service() -> DiarizationService:
    """Get or create the diarization service singleton."""
    global _diarization_service

    if _diarization_service is None:
        provider = os.getenv("DIARIZATION_PROVIDER", "deepgram")
        _diarization_service = DiarizationService(provider)

    return _diarization_service
