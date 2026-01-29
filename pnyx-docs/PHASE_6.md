# Phase 6: UX Polish, Fixes & Confidence (Future)

**Status:** 📋 **PLANNED**
**Focus:** User Experience, Q&A Reliability, Linking
**Prerequisite:** Phase 5 (Stabilization) must be complete.

---

## 1. Goal
Once the core engine is stable (Phase 5), Phase 6 focuses on the "Fit and Finish." We will address the "rough edges" in the Linking UX, improve the reliability of the Q&A feature, and add confidence indicators to the UI.

## 2. Scope of Work

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

## 3. Success Metrics
*   **Linking Time:** Users spend < 10s linking a meeting.
*   **Answer Satisfaction:** "Thumbs Up" rate on AI answers > 80%.
*   **UI Fluidity:** 60fps scrolling on meetings with 10k+ words.
