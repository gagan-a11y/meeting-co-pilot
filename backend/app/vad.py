"""
Simple Voice Activity Detection (VAD) based on audio amplitude.
Fast and lightweight alternative to Silero VAD for MVP.
"""

import numpy as np
import logging
from typing import List

logger = logging.getLogger(__name__)

class SimpleVAD:
    """
    Amplitude-based Voice Activity Detection.

    Detects speech by measuring audio energy/volume.
    Fast and simple - perfect for MVP. Can upgrade to Silero later.
    """

    def __init__(self, threshold: float = 0.02, sample_rate: int = 16000):
        """
        Args:
            threshold: RMS amplitude threshold (0.0-1.0)
                      0.01 = very sensitive, 0.05 = less sensitive
            sample_rate: Audio sample rate in Hz
        """
        self.threshold = threshold
        self.sample_rate = sample_rate
        logger.info(f"✅ SimpleVAD initialized (threshold={threshold})")

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        """
        Check if audio chunk contains speech.

        Args:
            audio_chunk: NumPy array of audio samples (int16 or float32)

        Returns:
            True if speech detected, False if silence
        """
        # Convert to float if needed
        if audio_chunk.dtype == np.int16:
            audio_float = audio_chunk.astype(np.float32) / 32768.0
        else:
            audio_float = audio_chunk

        # Calculate RMS (Root Mean Square) energy
        rms = np.sqrt(np.mean(audio_float ** 2))

        # Check if above threshold
        is_speech = rms > self.threshold

        return is_speech

    def get_speech_segments(
        self,
        audio: np.ndarray,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 500
    ) -> List[dict]:
        """
        Get timestamps of speech segments in audio.

        Args:
            audio: Full audio array
            min_speech_duration_ms: Minimum speech duration (ms)
            min_silence_duration_ms: Minimum silence to split segments (ms)

        Returns:
            List of {'start': ms, 'end': ms} dicts
        """
        # Process in chunks
        chunk_duration_ms = 100  # 100ms chunks
        chunk_size = int((chunk_duration_ms / 1000) * self.sample_rate)

        segments = []
        current_segment_start = None
        silence_duration = 0

        for i in range(0, len(audio), chunk_size):
            chunk = audio[i:i + chunk_size]
            if len(chunk) < chunk_size:
                break

            is_speech = self.is_speech(chunk)
            timestamp_ms = (i / self.sample_rate) * 1000

            if is_speech:
                silence_duration = 0
                # Start new segment if not in one
                if current_segment_start is None:
                    current_segment_start = timestamp_ms
            else:
                # Accumulate silence
                silence_duration += chunk_duration_ms

                # End segment if silence long enough
                if current_segment_start is not None and silence_duration >= min_silence_duration_ms:
                    segment_duration = timestamp_ms - current_segment_start

                    # Only add if long enough
                    if segment_duration >= min_speech_duration_ms:
                        segments.append({
                            'start': int(current_segment_start),
                            'end': int(timestamp_ms)
                        })

                    current_segment_start = None

        # Add final segment if exists
        if current_segment_start is not None:
            final_timestamp = (len(audio) / self.sample_rate) * 1000
            segment_duration = final_timestamp - current_segment_start
            if segment_duration >= min_speech_duration_ms:
                segments.append({
                    'start': int(current_segment_start),
                    'end': int(final_timestamp)
                })

        return segments


class SileroVAD:
    """
    Placeholder for Silero VAD (advanced ML-based VAD).

    We'll use SimpleVAD for MVP since Silero requires torch/torchaudio
    which take a long time to install. Can upgrade later.
    """

    def __init__(self, threshold: float = 0.5):
        logger.warning(
            "⚠️  Silero VAD not available (requires torch). "
            "Using SimpleVAD instead. Install torch for better accuracy."
        )
        # Fallback to SimpleVAD
        self.vad = SimpleVAD(threshold=threshold * 0.05)  # Convert 0.5 → 0.025

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        return self.vad.is_speech(audio_chunk)

    def get_speech_segments(self, audio: np.ndarray) -> List[dict]:
        return self.vad.get_speech_segments(audio)
