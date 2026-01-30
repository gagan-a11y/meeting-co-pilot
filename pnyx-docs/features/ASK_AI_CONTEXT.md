# Ask AI Context Strategy

**Last Updated:** January 12, 2026

This document explains how the Ask AI feature handles context for different query types.

---

## Overview

The Ask AI feature uses a **smart context strategy** that balances accuracy with efficiency:

| Query Type | Trigger | Context Source | Description |
|------------|---------|----------------|-------------|
| **Current Meeting** | Always | Frontend/DB | Full transcript, no limits |
| **Linked Meetings** | Keywords | DB (full transcripts) | When user explicitly asks |
| **Global Search** | Keywords | Vector Store (20 chunks) | Search across all meetings |
| **Web Search** | Keywords | SerpAPI + Gemini | External real-time info |

---

## Context Flow Diagram

```
User asks question
        ↓
┌─────────────────────────────────────────────┐
│ Check for "search on web" keywords          │ → Web search (SerpAPI)
└─────────────────────────────────────────────┘
        ↓ (no match)
┌─────────────────────────────────────────────┐
│ Check for "search all meetings" keywords    │ → Vector search (20 chunks)
└─────────────────────────────────────────────┘
        ↓ (no match)
┌─────────────────────────────────────────────┐
│ Check for linked meeting keywords           │ → Fetch full DB transcripts
│ + User has linked meetings                  │
└─────────────────────────────────────────────┘
        ↓ (no match)
┌─────────────────────────────────────────────┐
│ Use current meeting context only            │ → Full transcript
└─────────────────────────────────────────────┘
        ↓
Pass all context to Gemini 2.0 Flash
```

---

## Trigger Keywords

### Web Search
- `"search on web"`, `"find on web"`

### Global Search (Vector Store)
- `"search all meetings"`, `"search in all meetings"`
- `"search globally"`, `"global search"`
- `"find in all meetings"`, `"search across meetings"`

### Linked Meetings (Full Transcripts)
- `"search in linked meetings"`, `"linked meetings"`, `"search linked"`
- `"previous meeting"`, `"last meeting"`, `"other meeting"`
- `"compare"`, `"comparison"`, `"different from"`
- `"history"`, `"past"`, `"previously discussed"`
- `"follow up"`, `"what did we say"`, `"mentioned before"`

---

## Context Limits

**No limits!** Gemini 2.0 Flash has a 1M+ token context window.

### Token Estimation

| Scenario | Est. Tokens | % of Limit |
|----------|-------------|------------|
| 30-min meeting | ~7K-10K | ~1% |
| 1-hour meeting | ~15K-20K | ~2% |
| 3-hour meeting | ~36K | ~3.5% |
| 6 linked meetings (3hr each) | ~216K | **~22%** |

Even the extreme case (6 x 3-hour meetings) uses only 22% of Gemini's limit.

---

## Grounded Prompt Strategy

The system prompt prevents hallucinations while being helpful:

```
You are a helpful meeting assistant. Use the provided context to answer questions accurately.

RULES:
1. Answer based on the meeting context provided below - use ALL relevant information
2. When summarizing, include key points, decisions, action items, and important details
3. If citing linked meetings, use the source format shown in brackets
4. Do NOT invent information that isn't in the context
5. Be helpful and thorough in your responses
```

---

## Conversation History

Uses **first 2 + last 8** messages (total 10) for:
- **First 2:** Initial context/intent
- **Last 8:** Recent conversation flow

Each message limited to 1000 chars.

---

## Implementation Details

**File:** `backend/app/transcript_processor.py`

### Key Functions

| Function | Purpose |
|----------|---------|
| `chat_about_meeting()` | Main chat handler with context strategy |
| `_needs_linked_context()` | Keyword detection for linked meetings |
| `search_web()` | Web search via SerpAPI + Gemini |

### Data Sources

| Context Type | Source |
|--------------|--------|
| Current meeting | `context` param from frontend |
| Linked meetings | `db.get_meeting(meeting_id)` |
| Global search | `vector_store.search_context()` |

---

## Usage Examples

### Example 1: Simple Question (Current Only)
```
User: "What were the action items?"
→ Uses: Current meeting full transcript only
→ Tokens: ~15K (1 hour meeting)
```

### Example 2: Linked Meeting Search
```
User: "Search in linked meetings for budget discussion"
→ Uses: Current + All linked meeting full transcripts
→ Tokens: ~60K (3 linked 1-hour meetings)
```

### Example 3: Global Search
```
User: "Search all meetings for project deadline"
→ Uses: Current + 20 chunks from vector store
→ Tokens: ~40K
```

### Example 4: Web Search
```
User: "Search on web for latest AI news"
→ Uses: SerpAPI + page crawling + Gemini synthesis
→ No meeting context needed
```

---

## Related Documents

- [FUTURE_OPTIMIZATIONS.md](./FUTURE_OPTIMIZATIONS.md) - P0/P1/P2 optimization backlog
- [CROSS_MEETING_SEARCH.md](./CROSS_MEETING_SEARCH.md) - Vector store architecture
- [CHAT_MEMORY_ARCHITECTURE.md](./CHAT_MEMORY_ARCHITECTURE.md) - Chat history handling
