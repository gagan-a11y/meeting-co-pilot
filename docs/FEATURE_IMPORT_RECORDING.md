# Feature: Import Meeting Recording

**Status**: Planning
**Date**: Jan 29, 2026

## Overview
Allow users to upload existing audio or video files (e.g., Zoom recordings, voice memos) to Meeting Co-Pilot. The system will process these files to generate transcripts, speaker diarization, and AI summaries, effectively treating them as "past meetings".

## User Workflow
1. **Initiate**: User clicks "Import Recording" button on the dashboard/sidebar.
2. **Upload**: User selects a file (mp3, wav, m4a, mp4, webm) via drag-and-drop or file picker.
3. **Configuration**: User optionally sets:
   - Meeting Title (default to filename)
   - Number of speakers (hint for diarization)
   - Language (optional, auto-detect default)
4. **Processing**:
   - File uploads to server.
   - User sees a "Processing" state card in the meeting list.
   - Backend processes audio (convert -> transcribe -> diarize -> summarize).
5. **Completion**:
   - Notification when ready.
   - Meeting appears in list as a normal meeting.
   - User can view transcript and AI notes.

## Technical Architecture

### 1. Frontend
**Components**:
- `ImportDialog`: Modal with file dropzone.
- `FileUploadProgress`: Visual indicator of upload %.
- `MeetingListItem`: Update to show "Processing" state for pending imports.

**API Integration**:
- `POST /upload-meeting-recording`: Multipart form data upload.
- Polling mechanism (or WebSocket) to check processing status.

### 2. Backend API
**Endpoint**: `POST /upload-meeting-recording`
- **Input**: File, Title.
- **Validation**: Check file type, size limit (e.g., 500MB).
- **Storage**: Save raw file to `data/uploads/{uuid}/`.
- **Response**: Returns `meeting_id` immediately with status `processing`.
- **Background Task**: Triggers `process_uploaded_recording`.

### 3. Processing Pipeline (Background)
Reuses existing services where possible.

1. **Audio Conversion**:
   - Use `ffmpeg` to convert input -> WAV (16kHz, mono/stereo).
   - Optimize for Whisper (16kHz).
   
2. **Transcription**:
   - Call `GroqTranscriptionClient.transcribe_file(wav_file)`.
   - *Note*: Streaming logic is for live audio. For files, we can send larger chunks or the whole file if supported, or chunk it manually.
   
3. **Diarization**:
   - Call `DiarizationService.diarize_meeting()`.
   - Align transcripts with speakers.
   
4. **Summarization**:
   - Call `SummarizationService` to generate notes from transcript.
   
5. **Finalization**:
   - Update `meetings` table status to `completed`.
   - Store results in `transcript_segments` and `meeting_summaries`.

### 4. Database Schema
**Updates**:
- `meetings` table:
  - Add `source` column (`live` | `upload`).
  - Add `processing_status` (`completed` | `processing` | `failed`).
  - Add `file_path` (optional, if we keep source files).

## Implementation Steps

### Phase 1: Basic Upload & Transcribe
- [ ] Create `POST /upload-meeting-recording` endpoint.
- [ ] Implement file saving and FFmpeg conversion.
- [ ] Connect to Whisper API for full file transcription.
- [ ] Save transcript to DB.

### Phase 2: Frontend Integration
- [ ] Create "Import" button in Sidebar.
- [ ] Build Upload Modal.
- [ ] Handle "Processing" state in Meeting List.

### Phase 3: Advanced Pipeline
- [ ] Trigger Diarization after transcription.
- [ ] Trigger Summarization after diarization.
- [ ] Add vector embedding indexing.

### Phase 4: Polish
- [ ] Progress bars.
- [ ] Error handling (invalid files, API failures).
- [ ] File cleanup (delete uploads after processing).
