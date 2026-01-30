# Phase 8: UX Polish, Production Infrastructure & Deployment

**Status:** 📋 **PLANNED**
**Focus:** User Experience, Cloud Infrastructure, Production Readiness
**Prerequisite:** Phase 7 (Context Aware Chat) must be complete.

---

## 1. Goal
With the core features (Transcription, Diarization, Import, Context Chat) complete, Phase 8 focuses on "Fit and Finish," moving from local storage to cloud infrastructure, and deploying the application to production.

## 2. Infrastructure & Deployment (New)

### A. Cloud Storage Migration
**Current State:** Uploaded recordings are stored locally in `data/uploads/`.
**The Fix:** Migrate to **Google Cloud Storage (GCS)** buckets.
*   **Secure Uploads:** Generate signed URLs for frontend direct uploads (bypassing backend bottleneck).
*   **Lifecycle Management:** Auto-archive or delete old raw audio files after processing to save costs.
*   **Security:** Private buckets with strictly scoped IAM roles for the backend.

### B. Production Deployment
**Current State:** Running on localhost (Docker/Dev mode).
**The Plan:**
*   **Backend:** Deploy FastAPI on Cloud Run (serverless) or a dedicated VM (if persistent GPU needed, though we use Groq/Deepgram APIs so CPU-only is fine).
*   **Frontend:** Deploy Next.js to Vercel or Cloud Run.
*   **Database:** Migrate SQLite to managed PostgreSQL (e.g., Supabase, Neon, or Cloud SQL).
*   **Domain & SSL:** Configure `pnyx.io` (or similar) with proper HTTPS.

---

## 3. UX Polish & Reliability (Previously Phase 6)

### A. Linking UX Revamp
**Current State:** Functional but clunky list selection.
**The Fix:**
*   **Smart Suggestions:** "Based on the participants/title, this meeting seems related to..."
*   **Visual Graph:** Simple node-link view of related meetings.
*   **One-Click Context:** "Add context from last week's sync" button.

### B. Q&A Reliability (RAG Improvements)
**Current State:** Working but prone to hallucinations or missing context.
**The Fix:**
*   **Citation Mode:** Every answer must link back to a specific timestamp in a transcript.
*   **Negative Constraints:** Teach the AI to say "I don't know" instead of guessing.
*   **Query Expansion:** Automatically broaden user searches (e.g., "roadmap" -> "timeline", "plans", "Q3 goals").

### C. Confidence-Aware UX
**Current State:** Text looks "final" instantly.
**The Fix:**
*   **Visual States:**
    *   *Gray Text:* "I'm still listening / processing."
    *   *Black Text:* "I am reasonably sure."
    *   *Green Check:* "Verified by human or Gold Standard."
*   **Speaker Avatars:** Group consecutive segments visually instead of repeating "Speaker A".

### D. General Fixes (The "And All")
*   **Export:** PDF/Markdown export with proper formatting.
*   **Performance:** Virtualize the transcript list for long meetings (reduce DOM nodes).
*   **Mobile View:** Ensure the "Read-Only" link works perfectly on mobile phones.

## 4. Success Metrics
*   **Deployment:** Fully automated CI/CD pipeline.
*   **Scalability:** Can handle concurrent file uploads without crashing.
*   **Linking Time:** Users spend < 10s linking a meeting.
*   **Answer Satisfaction:** "Thumbs Up" rate on AI answers > 80%.
