# Testing Nuanced Context Awareness (Query Reformulation)

**Status:** ✅ Implemented
**Date:** Jan 30, 2026

The Chatbot now includes **Contextual Query Reformulation**. Before processing any request, it rewrites the user's question to resolve pronouns ("it", "this", "they") based on the chat history. This prevents the "Eat Hot Chip" error where vague queries were searched literally.

## 1. Why this matters
*   **Old Behavior:**
    *   User: "We need to fix API timeouts." -> AI: "OK."
    *   User: "Search web for how to fix **it**." -> AI searches for "how to fix **it**" -> Irrelevant results.
*   **New Behavior:**
    *   User: "We need to fix API timeouts." -> AI: "OK."
    *   User: "Search web for how to fix **it**."
    *   **System Reformulates:** "Search web for how to fix **API timeouts**."
    *   **Search Tool:** Searches "how to fix API timeouts". -> Useful results.

---

## 2. Test Cases for Nuance

### Test Case A: The "Pronoun Follow-up" (The Fix for your issue)
*   **Step 1:** Ask a specific question.
    *   *Prompt:* "What is the capital of Australia?"
    *   *AI Answer:* "Canberra."
*   **Step 2:** Ask a vague follow-up with a search trigger.
    *   *Prompt:* "Search for its population."
*   **Expected Result:**
    *   **UI Status:** `🔍 Searching web for: *population of Canberra*...` (or *population of Australia*)
    *   **Success:** It does **NOT** search for "its population".

### Test Case B: The "List & Pick"
*   **Step 1:** Ask for a list.
    *   *Prompt:* "List three popular python web frameworks."
    *   *AI Answer:* "Django, Flask, FastAPI."
*   **Step 2:** Refer to one item implicitly.
    *   *Prompt:* "Which one is the fastest?"
*   **Expected Result:**
    *   **Internal logic:** Reformulates to "Which of Django, Flask, FastAPI is the fastest?"
    *   **Web Search (Implicit):** Should likely trigger web search for benchmarks.
    *   **UI Status:** `🔍 Searching web for: *fastest python web framework benchmark*...`

### Test Case C: Technical Troubleshooting (Your Scenario)
*   **Step 1:** Establish context.
    *   *Prompt:* "We are seeing high latency in our Postgres database queries."
*   **Step 2:** Ask for a solution using vague terms.
    *   *Prompt:* "Find solutions for this on google."
*   **Expected Result:**
    *   **UI Status:** `🔍 Searching web for: *solutions for high latency in Postgres database queries*...`
    *   **Answer:** Returns technical articles about Postgres optimization (indexes, vacuum, etc.), not generic "solutions for this".

---

## 3. How it works (Under the hood)
1.  **Intercept:** Chat endpoint receives the raw question.
2.  **Reformulate:** Calls Gemini Flash with the last 3 messages + current question.
3.  **Instruction:** "Rewrite to be standalone. Resolve pronouns."
4.  **Execute:** The *rewritten* query is what gets sent to the Search Router and the Web Search Tool.
