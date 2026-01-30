# Cloud Storage Migration Plan (GCP)

**Status:** 📋 Planning / Implementation
**Date:** Jan 30, 2026
**Goal:** Migrate meeting audio storage from local filesystem to Google Cloud Storage (GCS) for scalability and security.

---

## 1. Architecture Overview

We are moving from a **Local Storage** model to a **Cloud Hybrid** model.

*   **Current (Local):** `backend/data/recordings/{meeting_id}/chunk_X.pcm`
*   **Target (GCP):**
    *   **Live Recording:** Stored temporarily on local disk (for low latency).
    *   **Archival:** Merged audio is uploaded to GCS bucket (`gs://<bucket>/{meeting_id}/recording.wav`).
    *   **Playback:** Served via **Signed URLs** (time-limited, private links).

### Security Architecture (User Isolation)
*   **Bucket Privacy:** The GCS bucket will have **"Public Access Prevention" enabled**. No file is publicly accessible.
*   **Access Control:**
    1.  Frontend requests audio URL for a specific meeting.
    2.  Backend checks `RBAC` permissions (User = Owner?).
    3.  Backend generates a **Signed URL** valid for 60 minutes.
    4.  Frontend plays audio using this temporary URL.
    *   *Result:* Users can only hear recordings they own. Sharing the URL works only temporarily.

---

## 2. Prerequisites (Configuration)

Before code implementation, the following GCP resources must be set up:

### A. Create GCS Bucket
1.  **Name:** `meeting-copilot-recordings` (recommended).
2.  **Region:** `us-central1` (or matching your server).
3.  **Storage Class:** Standard.
4.  **Security:** **Enforce public access prevention**.

### B. Service Account
1.  Create Service Account: `storage-admin`.
2.  Role: **Storage Object Admin**.
3.  **Key:** Create JSON key and save as `backend/gcp-service-account.json`.

---

## 3. Implementation Plan

### Step 1: Storage Abstraction Layer (`backend/app/storage.py`)
Create a new module to handle all file operations, decoupling the logic from the filesystem.

```python
class StorageService:
    def upload_file(self, local_path, destination_blob): ...
    def download_file(self, blob_name, local_destination): ...
    def delete_file(self, blob_name): ...
    def generate_signed_url(self, blob_name, expiration=3600): ...
```

### Step 2: Hybrid Audio Recorder
Update `AudioRecorder` to support the upload lifecycle:
1.  **Recording:** Keep saving chunks locally to `temp/` (fast I/O).
2.  **On Stop:**
    *   Merge chunks -> `merged.wav`.
    *   **Upload** `merged.wav` to GCS.
    *   **Cleanup** local chunks.

### Step 3: Processing Pipeline Updates
Update `diarization_job` and `transcription_job`:
*   **Input:** Check if file is local. If not, **download** from GCS to a temp worker directory.
*   **Process:** Run FFmpeg/Whisper.
*   **Cleanup:** Delete temp input file.

### Step 4: Playback Endpoint
New API endpoint for frontend:
*   `GET /meetings/{id}/recording-url`
*   Returns: `{ "url": "https://storage.googleapis.com/...Signature=..." }`

---

## 4. Migration Script (Legacy Data)
A script `scripts/migrate_to_gcp.py` will be created to:
1.  Scan `data/recordings/`.
2.  Merge chunks for old meetings.
3.  Upload to GCS.
4.  Update Database `audio_url` or flag.
5.  Archive local files.

---

## 5. Environment Variables

Add to `.env`:
```bash
STORAGE_TYPE=gcp  # or 'local'
GCP_BUCKET_NAME=meeting-copilot-recordings
GOOGLE_APPLICATION_CREDENTIALS=gcp-service-account.json
```
