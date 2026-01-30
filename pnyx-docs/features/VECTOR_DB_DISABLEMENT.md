# Vector DB Disablement (Jan 30, 2026)

**Purpose:** To temporarily disable all Vector Database operations (embeddings generation and vector search) while retaining the code for future re-enablement.

## Changes Made

### 1. Backend (`backend/app/main.py`)

#### A. Disabled Embedding Storage
In `process_transcript_background` (approx. line 574), commented out the block calling `store_meeting_embeddings`.
*   **Effect:** Meetings are processed and summarized, but no vectors are generated or stored in Postgres.

#### B. Disabled Context Search
In `search_context_endpoint` (approx. line 1217), commented out `search_context` call.
*   **Effect:** The `/search-context` endpoint returns an empty result list `[]` instead of querying the vector store.
*   **Note:** The Sidebar Search uses `/search-transcripts` which relies on SQL `LIKE` queries, so it is **unaffected** and continues to work.

#### C. Disabled Re-indexing
In `reindex_vector_db` (approx. line 2349), commented out the entire logic.
*   **Effect:** Triggering this endpoint returns a "skipped" status message.

## How to Re-enable

To re-enable Vector DB functionality, uncomment the code blocks in `backend/app/main.py`:

1.  **Storage:** Uncomment lines ~574-592.
2.  **Search:** Uncomment lines ~1224-1239.
3.  **Re-indexing:** Uncomment lines ~2357-2453.

## Why SQL for Sidebar?
The sidebar search uses the `/search-transcripts` endpoint. This endpoint was already implemented using SQL `LIKE` queries in `db.search_transcripts`, scanning both `transcript_segments` and `full_transcripts` tables. Therefore, disabling the vector store does not break the primary search functionality.
