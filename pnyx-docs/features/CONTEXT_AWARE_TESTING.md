# Testing Context-Aware Chat & Search

**Status:** ✅ Implemented
**Date:** Jan 30, 2026

The Chat system has been upgraded to a **Router-based Hybrid Architecture**. It now intelligently decides whether to search the web, check linked meetings, or answer from the current context.

## 1. What's New?

| Feature | Old Behavior | New Behavior |
| :--- | :--- | :--- |
| **Web Search** | Triggered ONLY by "search for..." | Triggered **automatically** by questions requiring external facts (e.g., "What is the price of X?"). |
| **Response Style** | Returned raw search results. | **Synthesizes** search results with meeting context (e.g., "Unlike our budget of $5k, the market average is $10k..."). |
| **Hybrid Query** | Impossible. | Possible (e.g., "Compare our timeline [Meeting] with the Apple release schedule [Web]"). |

---

## 2. How to Test Efficiently

### Test Case A: implicit Web Search (The "Router" Test)
*   **Goal:** Verify the system detects the need for search without being told.
*   **Prompt:** `"Who is the CEO of OpenAI?"` or `"What is the current price of Bitcoin?"`
*   **Expected Behavior:**
    1.  UI shows: `🔍 Searching web for: *CEO of OpenAI*...`
    2.  AI answers: "Sam Altman is the CEO..." (citing a web source).

### Test Case B: Hybrid Context (The "Synthesis" Test)
*   **Goal:** Verify the system combines internal and external data.
*   **Prerequisite:** Have a meeting where you mention a specific budget (e.g., "Our marketing budget is $5,000").
*   **Prompt:** `"Is our marketing budget enough for a Super Bowl ad?"`
*   **Expected Behavior:**
    1.  UI shows: `🔍 Searching web for: *Super Bowl ad cost*...`
    2.  AI answers: "No. Your budget is **$5,000** [Meeting], but a Super Bowl ad costs approx **$7M** [Web Source]."

### Test Case C: Explicit Search (The "Override" Test)
*   **Goal:** Verify manual commands still work.
*   **Prompt:** `"Search on web for best react libraries."`
*   **Expected Behavior:**
    1.  UI shows: `🔍 Searching web for: *best react libraries*...`
    2.  AI lists libraries with web citations.

### Test Case D: Linked Meeting Context
*   **Goal:** Verify cross-meeting intelligence.
*   **Prerequisite:** Link a previous meeting using the link button.
*   **Prompt:** `"What did we decide about the roadmap in the last meeting?"`
*   **Expected Behavior:**
    1.  System fetches full transcript of the linked meeting.
    2.  AI answers using details from that specific meeting.

---

## 3. Troubleshooting

*   **"It didn't search!"** -> The router (Gemini Flash) might have classified it as a "MEETING" question. Try being more specific: "Search for..."
*   **"It hallucinated!"** -> Check if the UI showed the "Searching..." message. If not, it didn't fetch external data.
*   **"Search failed"** -> Check backend logs for `SerpAPI` errors (quota limits or key missing).
