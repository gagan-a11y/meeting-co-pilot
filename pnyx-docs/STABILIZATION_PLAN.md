# PNYX – Diarization & Transcription Stabilization Plan

**Status:** Draft / Proposed  
**Author:** Staff Architect (AI Agent)  
**Date:** January 28, 2026

---

## 1. Purpose of This Document
The PNYX meeting copilot has evolved from a simple recorder to a complex AI agent. While individual components (Groq transcription, TenVAD, Gemini summarization) are high-quality, the end-to-end reliability is unstable. Users experience timestamp drifts, duplicate transcriptions, and occasional data loss.

**This document defines the roadmap to stabilize the core recording and transcription engine before any new features are added.** We must stop "building on quicksand."

## 2. Non-Goals
We are **NOT** trying to solve:
- **Perfect Real-Time Diarization:** We accept that live transcripts will be speaker-agnostic or have "best guess" labels. High-fidelity attribution happens post-meeting.
- **Multi-User Real-Time Sync:** We are optimizing for a single host recording the meeting.
- **Offline-Only Mode:** We rely on cloud APIs (Groq, Deepgram, Gemini) for quality and speed.

## 3. Current System Summary (As-Is)
*   **Audio Capture:** Browser `MediaRecorder` (WebM) → WebSocket → Backend.
*   **Live Transcription:**
    *   Audio chunks converted to 16kHz PCM.
    *   **TenVAD** detects speech.
    *   **Rolling Buffer** (12s window, 1.5s overlap) accumulates audio.
    *   **Groq API (Whisper Large v3)** transcribes the buffer.
    *   **Deduplication:** Hash-based and N-gram overlap checks to prevent repeating text.
*   **Recording:** Parallel `AudioRecorder` saves 30s chunks to disk.
*   **Post-Meeting:**
    *   User triggers "Diarize".
    *   Chunks merged to WAV.
    *   **Hybrid Analysis:** Full audio sent to Whisper (Text) and Deepgram (Speakers).
    *   Results aligned and DB updated.

**Failure Modes:**
*   **Timestamp Drift:** Live timestamps are often wall-clock time, while post-processed are audio-relative, causing UI jumps.
*   **Over-Deduplication:** "Yeah... Yeah" might be filtered out as a duplicate even if valid.
*   **Race Conditions:** Rapid start/stop events can leave the `AudioRecorder` or `WebSocket` in inconsistent states.

## 4. Root Cause Analysis
1.  **Over-trust in Live Timestamps:** We treat the reception time of a WebSocket packet as the "spoken time," ignoring network jitter and VAD processing delays.
2.  **Fragile Alignment Logic:** The post-meeting alignment assumes Whisper and Deepgram segments will line up linearly. Packet loss or silence removal breaks this assumption.
3.  **VAD Authority Conflicts:** Both the local VAD (TenVAD) and the remote API (Groq/Whisper) have opinions on "silence." When they disagree, we get cut-off words.
4.  **Mutable Transcripts:** We tend to overwrite the "live" transcript with the "diarized" one, making debugging impossible if the diarization messes up.

## 5. Design Principles Going Forward
1.  **Live = Approximate:** Live transcripts are for *human readability now*. They are disposable.
2.  **Post = Authoritative:** The post-meeting "Gold Standard" run is the source of truth.
3.  **Never Force Attribution:** "Unknown Speaker" is better than "Wrong Speaker."
4.  **Silence > Wrong Attribution:** If we can't match text to a speaker, it's a floating comment, not an error.
5.  **Versioning:** Keep the "Raw Live Transcript" in the DB even after generating the "Diarized Transcript."

## 6. Revised Architecture (To-Be)

**What Stays:**
- Groq for Live Transcription (Unbeatable speed).
- Deepgram for Diarization (Best speaker separation).
- Gemini for Summarization.

**What Changes:**
- **Timestamp Protocol:** Frontend sends `audio_start_time` (context time) with every chunk. Backend uses *that*, not server time.
- **Session Linking:** `AudioRecorder` and `TranscriptionManager` share a strict `session_id` and `start_time` reference.
- **Dual-Stream DB:**
    - Table `live_transcripts` (Immutable log of what happened live).
    - Table `refined_transcripts` (The clean, diarized version).
    - UI toggles between them (or defaults to Refined if available).

## 7. Phase-wise Execution Plan

### Phase 4: Stabilization (Weeks 1-2)
**Goal:** Zero data loss, accurate timestamps.
- **In-Scope:**
    - Standardize timestamp format `(MM:SS)` everywhere (Backend, Frontend, DB).
    - Implement "client-side time" for audio chunks to fix drift.
    - Add "Heartbeat" to WebSocket to detect ghost connections.
- **Metrics:** 0 reports of "missing end of sentence"; timestamps match audio player within 0.5s.

### Phase 5: Diarization Reliability & UX Polish (Week 3)
**Goal:** "Gold Standard" pipeline reliability and **improvement of the rough Linking UX**.
- **In-Scope:**
    - Implement the "Hybrid Alignment" with fuzzy matching (Levenshtein distance) for words.
    - Handle cases where Whisper segments > Deepgram segments (1-to-many mapping).
    - **Linking UX Revamp:** Streamline the interface for connecting related meetings.
    - Add "Raw Audio Export" button for debugging.
- **Metrics:** Alignment success rate > 95%; Linking task completion time reduced by 50%.

### Phase 6: Confidence-Aware UX (Week 4)
**Goal:** UI reflects the certainty of the data.
- **In-Scope:**
    - Visual indicator for "Live" vs "Verified" transcripts.
    - "Low Confidence" graying out for uncertain words.
    - "Unknown Speaker" avatar grouping.

## 8. Data Model Changes
- **New Table:** `transcript_versions`
    - `id`, `meeting_id`, `version_number`, `source` (live/diarized), `content` (JSON), `created_at`.
- **Columns:**
    - Add `client_timestamp_ms` to `audio_chunks` table.

## 9. Risks & Mitigations
- **Risk:** Browser clock skew.
    - **Mitigation:** Sync time on connection; use relative time (`performance.now()`) for audio chunks.
- **Risk:** Huge meetings (2+ hours) crash the alignment.
    - **Mitigation:** Chunk alignment process into 10-minute windows.

## 10. Open Questions
- Should we allow users to manually edit the "Refined" transcript? (Yes, but how do we version that?)
- Do we support "Stereo" recording if the user has a sophisticated mic setup? (Deferred).

---

## Execution Readiness Checklist

### For Engineers
- [ ] Verify `ffmpeg` is installed and version 5+ in Docker.
- [ ] Check `Groq` and `Deepgram` API quotas.
- [ ] Run `test_audio.py` (if exists) or create a baseline test script.

### For Product
- [ ] Approve the "Single Host" pivot in messaging.
- [ ] Accept that "Live Speaker ID" is not in this version.

### Merge Safety
- Use `ENABLE_V2_PIPELINE` env var to toggle the new logic.
- Keep the old `save_transcript` endpoint active until Phase 4 is verified.
