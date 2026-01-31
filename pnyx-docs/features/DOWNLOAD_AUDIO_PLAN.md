# Plan: Convert "Open Folder" to "Download Audio"

**Objective:** Replace the legacy "Open Meeting Folder" button (which fails on web) with a functioning "Download Recording" button that works with Cloud Storage.

## Implementation Steps

1.  **Update Logic (`useMeetingOperations.ts`):**
    *   Remove `handleOpenMeetingFolder` (and the "Opening local folders not supported" toast).
    *   Add `handleDownloadRecording`:
        *   Call `GET /meetings/{id}/recording-url` to get a signed URL.
        *   Trigger a browser download (create secure link element and click).

2.  **Update UI (`TranscriptButtonGroup.tsx`):**
    *   **Icon:** Replace `FolderOpen` with `Download`.
    *   **Label:** Change "Recording" to "Download".
    *   **Tooltip:** Change to "Download Audio File".

3.  **Prop Drilling:**
    *   Rename `onOpenMeetingFolder` prop to `onDownloadRecording` in:
        *   `TranscriptButtonGroup.tsx`
        *   `TranscriptPanel.tsx`
        *   `PageContent.tsx`
