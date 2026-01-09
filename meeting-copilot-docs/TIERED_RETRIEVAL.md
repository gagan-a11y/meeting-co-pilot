# Tiered Context Retrieval & Grounding

**Date:** January 8, 2026  
**Status:** Implemented

## Overview

The chat system uses **tiered retrieval** to intelligently fetch context based on query type, and **grounding prompts** to prevent hallucinations.

---

## Tier System

| Tier | When Used | Context Source |
|------|-----------|----------------|
| **Current** | Default queries | Current meeting transcript only |
| **Linked** | "last time", "follow up", "previously" | Linked/allowed meetings |
| **Global** | "ever", "any meeting", "history" | All meetings |

### Detection Logic

```python
# Global keywords trigger all-meeting search
"ever", "any meeting", "all meetings", "history", "have we discussed"

# Linked keywords trigger related meeting search  
"last time", "follow up", "previously", "yesterday", "last week"

# Everything else = current meeting only (default)
```

---

## Grounding Rules

The system prompt includes explicit grounding instructions:

```
CRITICAL RULES:
1. Answer ONLY using the provided meeting excerpts
2. If info is NOT in excerpts, say "I don't have that information"
3. Do NOT invent decisions, dates, or action items
4. Cite sources: "[Meeting Title (Date)]"
5. Acknowledge unclear/garbled transcripts
```

---

## Flow Diagram

```
┌─────────────────────────────────────────────────────┐
│                  User Query                          │
│                      ↓                               │
│           detect_context_tier()                      │
│           ┌─────────┼─────────┐                      │
│           ↓         ↓         ↓                      │
│       CURRENT    LINKED    GLOBAL                   │
│           ↓         ↓         ↓                      │
│      (no search) (allowed)  (all)                   │
│           └─────────┼─────────┘                      │
│                     ↓                                │
│           Build Grounded Prompt                      │
│                     ↓                                │
│              LLM Response                            │
└─────────────────────────────────────────────────────┘
```

---

## Files Modified

| File | Changes |
|------|---------|
| `backend/app/transcript_processor.py` | Added `detect_context_tier()`, modified `chat_about_meeting()` |

---

## Testing

1. **Current tier:** "What was discussed in this meeting?"
   - Should only use current transcript
   
2. **Linked tier:** "What did we decide last time?"
   - Should search linked meetings
   
3. **Global tier:** "Have we ever discussed API limits?"
   - Should search all meetings

4. **Grounding test:** Ask about something not in meetings
   - Should respond: "I don't have that information"
