# Phase 7: Context-Aware Chatbot & Search

**Status:** ✅ **COMPLETED**
**Completion Date:** Jan 30, 2026
**Focus:** RAG, Search Integration, Hallucination Prevention
**Design Doc:** [CONTEXT_AWARE_CHATBOT_WITH_SEARCH.md](../architecture/CONTEXT_AWARE_CHATBOT_WITH_SEARCH.md)

---

## 1. Goal
Build an advanced AI assistant that runs alongside meetings, capable of answering questions using three knowledge sources: **Live Meeting Context** (what's being said now), **Historical Context** (past meetings/VectorDB), and **External Web Intelligence** (search results).

## 2. Core Components

### A. Context Router (The "Brain")
*   **Function:** Decides *where* to look for an answer.
*   **Logic:**
    *   *Refers to now?* -> Query Live Transcript buffer.
    *   *Refers to past?* -> Query Vector DB (PGVector).
    *   *Requires facts/external info?* -> Trigger Web Search Tool.
    *   *Ambiguous?* -> Ask clarification or check multiple.

### B. Web Search Integration (The "Eyes")
*   **Tool:** Tavily API or Google Search API.
*   **Trigger:** Only triggered on explicit request ("Search for...") or detected factual debates.
*   **Privacy:** Query sanitization (remove PII) before sending to external search APIs.

### C. Hybrid Retrieval Strategy
*   **Mechanism:** Parallel query execution (Internal + External).
*   **Ranking:** Rerank results based on relevance to the current discussion.
*   **Synthesis:** LLM combines internal context + external facts into a single citation-backed answer.

## 3. Implementation Plan

### Step 1: Search Infrastructure
*   [x] Set up Search API (Tavily/Google).
*   [x] Implement `SearchService` in backend.
*   [x] Build "Debate Detector" prompt.

### Step 2: RAG Pipeline Upgrade
*   [x] Update `VectorDB` to support hybrid search.
*   [x] Implement `ContextRouter` logic in the Chat endpoint.
*   [x] Add citation tracking (source attribution).

### Step 3: Frontend Chat Interface
*   [x] Add "Searching..." UI state.
*   [x] Display citations/sources in chat bubbles.
*   [x] "Verify this" button for specific transcript segments.

## 4. Success Metrics
*   **Latency:** Answer generated < 4s (including search).
*   **Accuracy:** > 95% of claims have correct citations.
*   **Debate Resolution:** Successfully resolves conflicting statements in test scenarios.
