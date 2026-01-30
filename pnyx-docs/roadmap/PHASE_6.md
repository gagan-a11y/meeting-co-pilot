# Phase 6: Import Recording

**Status:** ✅ **COMPLETED**
**Completion Date:** Jan 29, 2026

---

## 1. Goal
Allow users to upload existing audio or video files (e.g., Zoom recordings, voice memos) to Meeting Co-Pilot. The system processes these files to generate transcripts, speaker diarization, and AI summaries, treating them as first-class citizens alongside live meetings.

## 2. Delivered Features

### A. File Upload Pipeline
*   **Endpoint:** `POST /upload-meeting-recording`
*   **Supported Formats:** mp3, wav, m4a, mp4, webm
*   **Processing:**
    1.  **Upload:** File stored locally (temp).
    2.  **Conversion:** `ffmpeg` converts to standardized 16kHz WAV.
    3.  **Transcription:** Groq Whisper Large v3 processes the file.
    4.  **Diarization:** Deepgram/AssemblyAI aligns speakers to text.
    5.  **Summarization:** LLM generates notes and action items.

### B. Integration
*   **Frontend:** "Import Recording" button in sidebar with drag-and-drop support.
*   **Status Tracking:** Meetings show "Processing" state until ready.
*   **Versioning:** Imported transcripts are versioned similarly to live ones.

### C. Technical Implementation
*   **Merged Recording Support:** System handles pre-recorded files (`merged_recording.wav`) differently from live chunked audio.
*   **Error Handling:** Robust handling for invalid files, large uploads, and API timeouts.

## 3. Related Documentation
*   [Feature Spec](../docs/FEATURE_IMPORT_RECORDING.md)
