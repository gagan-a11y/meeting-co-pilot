# Future Optimizations Reference

**Date:** January 8, 2026  
**Status:** Backlog (prioritized)

This document tracks potential optimizations for the transcription system, organized by priority.

---

## Priority Legend

| Priority | Meaning | When to Implement |
|----------|---------|-------------------|
| **P0** | Quick wins, high impact | Implement soon |
| **P1** | Important, but more effort | Plan for next sprint |
| **P2** | Nice to have | When specific trigger occurs |

---

# P0 — Quick Wins (Do First)

## 1. LLM Context Prompting ⚡

**Effort:** ~1-2 hours  
**Impact:** Better named entities, technical terms, continuity

Feed the last finalized transcript as context to the next transcription call.

```python
response = groq.transcribe(
    audio=audio_chunk,
    prompt=last_finalized_text[-300:]  # Last 200-300 chars
)
```

**Benefits:**
- "John" stays "John" not "Jon" or "Joan"
- "Kubernetes" not "Cube Netties"
- Project names stay consistent

**Considerations:** Verify Groq API supports `prompt` parameter.

---

## 2. Smart Timer Trigger Logic ⚡

**Effort:** ~2 hours  
**Impact:** Better sentence boundaries, faster finals

Replace fixed 8s timeout with multi-condition trigger:

```python
if silence_duration > 600:      # 600ms silence
    finalize("silence")
elif buffer_duration > 12000:   # 12s max
    finalize("timeout")
elif ends_with_punctuation(text) and buffer_duration > 3000:
    finalize("punctuation")
```

**Benefits:** Natural sentence breaks, handles fast talkers.

---

## 3. Grounded Prompt Strategy ⚡

**Effort:** ~30 minutes  
**Impact:** Prevents hallucinated decisions, invented action items

Explicitly tell the LLM to only use provided context:

```python
prompt = f"""You are a meeting assistant. Answer ONLY using the provided excerpts.

RULES:
1. Only answer based on the excerpts below
2. If information is missing, say "I don't have that information"
3. Do not invent decisions, dates, or action items
4. Cite which meeting the information came from

MEETING EXCERPTS:
{chunks}

QUESTION: {question}
"""
```

**Why P0:** Without grounding, LLMs fabricate plausible-sounding decisions. Critical for user trust.

---

# P1 — High Priority (Plan Next)

## 4. Time-Aligned Deduplication 🐛

**Effort:** ~4-6 hours  
**Impact:** Fixes accidental deletion of repeated words

**The Problem:** Current dedup can delete legitimate phrases:
- "Yes, yes, exactly" → "Yes, exactly" ❌
- "Go go go!" → "Go!" ❌

**Solution:** Only dedupe when time windows overlap AND text is similar:

```python
def should_dedupe(text_a, text_b, time_a, time_b):
    return has_time_overlap(time_a, time_b) AND ngram_similarity(text_a, text_b) > 0.7
```

**Why P1:** This is effectively a bug fix — users lose speech content.

---

## 5. Adaptive VAD Threshold

**Effort:** ~4-6 hours  
**Impact:** Cleaner transcripts in noisy environments

Dynamically adjust threshold based on rolling noise floor:

```python
speech_threshold = noise_floor + margin
is_speech = vad_score > speech_threshold
```

**Trigger:** Users report false triggers from fans, typing, AC.

---

## 6. Dual Buffer Strategy (Micro + Macro)

**Effort:** ~6-8 hours  
**Impact:** Better final accuracy, fewer hallucinations

| Buffer | Size | Purpose |
|--------|------|---------|
| Micro | 2s | Fast partial transcripts |
| Macro | 10-15s | Final transcription with context |

**Why:** Whisper with more context = better grammar, fewer hallucinated endings.  
**Trade-off:** Finals delayed by 10-15s, ~2x API calls.

---

## 7. Hybrid Retrieval (Semantic + Keyword)

**Effort:** ~3-4 hours  
**Impact:** Significantly better search for names, technical terms, exact phrases

**The Problem:** Vector-only search can miss exact keyword matches:

| Query | Vector might miss | BM25 catches |
|-------|-------------------|--------------|
| "API rate limits" | Finds "throttling" but misses exact phrase | Exact match |
| "John mentioned Kubernetes" | Finds similar topics | Exact name match |

**Solution:** Combine vector score with BM25 keyword score:

```python
final_score = alpha * vector_score + (1 - alpha) * bm25_score
# alpha = 0.5-0.7 typically works well
```

**Implementation Options:**
| Option | Effort | Notes |
|--------|--------|-------|
| `rank_bm25` library | ~2-3h | Lightweight, pure Python |
| LangChain Ensemble | ~1-2h | If using LangChain |
| Weaviate/Qdrant | ~4-6h | Replace ChromaDB (native hybrid) |

**Why P1:** Retrieval quality matters more than LLM choice. Essential for technical meetings.

---

## 8. Chunk Expansion (Context Window)

**Effort:** ~2-3 hours  
**Impact:** LLM sees full narrative arc, better decision extraction

**The Problem:** Retrieving isolated chunks gives incomplete context:
> "...so we decided to go with option B because..."

Missing: What was option A? What are next steps?

**Solution:** After retrieving top chunks, also pull previous/next:

```python
def expand_chunks(retrieved_ids, all_chunks):
    expanded = set()
    for chunk_id in retrieved_ids:
        idx = extract_index(chunk_id)  # "meeting_123_chunk_5" → 5
        expanded.add(idx - 1)  # Previous
        expanded.add(idx)      # Current  
        expanded.add(idx + 1)  # Next
    return [all_chunks[i] for i in sorted(expanded) if 0 <= i < len(all_chunks)]
```

**Result:** `[Context] → [Decision] → [Follow-up]`

**Why P1:** Low effort, high impact on action items and decision accuracy.

---

# P2 — Nice to Have (When Triggered)

## 9. VAD Timestamps

**Effort:** ~3 hours  
**Impact:** Enables diarization, subtitles, timeline

Store precise VAD-detected speech start/end times.

**Trigger:** Before adding diarization or timeline features.

---

## 10. Incremental Vector Store Updates

**Effort:** ~4 hours  
**Impact:** Faster meeting saves, less memory spike

Stream embeddings during recording instead of all at once.

**Trigger:** Very long meetings (1+ hour) cause slow saves.

---

## 11. Adaptive Buffer Sizing

**Effort:** ~4 hours  
**Impact:** Better latency/accuracy for varied speech patterns

Dynamically adjust buffer window based on speech patterns.

**Trigger:** After collecting real usage data.

---

## 12. Frontend Energy Gating

**Effort:** ~1 hour  
**Impact:** Reduced network traffic

Skip sending silent frames from frontend.

**Trigger:** Remote deployment, bandwidth issues, noisy mics.

---

## 13. WebSocket Binary Compression

**Effort:** ~2 hours  
**Impact:** 30-50% bandwidth reduction

Compress PCM audio with Opus/FLAC/LZ4.

**Trigger:** Remote deployment with bandwidth constraints.

---

## 14. Time-Weighted Ranking

**Effort:** ~1-2 hours  
**Impact:** Recent decisions rank higher than old ones

Boost recent meetings in search results for queries about "current" state.

```python
days_ago = (now - meeting_date).days
recency_boost = 1 / (1 + 0.01 * days_ago)  # Gentle decay
final_score = similarity * recency_boost
```

**Caution:** Use gentle decay. Aggressive recency can hurt queries like "When did we first discuss X?"

**Trigger:** Users pulling outdated decisions when recent ones exist.

---

## 15. LLM-Based Tier Classification

**Effort:** ~2-3 hours  
**Impact:** More accurate tier detection for nuanced queries

Replace keyword-based tier detection with a fast LLM classifier (Groq llama-3.1-8b-instant ~100ms).

**Current:** Keywords like "ever", "last time" trigger tiers  
**Proposed:** Small LLM classifies intent accurately

**When to Implement:**
- Keyword detection causes misclassifications
- Senior requests after demo

---

# Summary Table

| # | Optimization | Priority | Effort | Quick Win? |
|---|--------------|----------|--------|------------|
| 1 | LLM Context Prompting | **P0** | 1-2h | ⚡ Yes |
| 2 | Smart Timer Trigger | **P0** | 2h | ⚡ Yes |
| 3 | Grounded Prompt Strategy | **P0** | 30m | ⚡ Done ✅ |
| 4 | Time-Aligned Dedup | **P1** | 4-6h | Bug fix |
| 5 | Adaptive VAD Threshold | **P1** | 4-6h | |
| 6 | Dual Buffer Strategy | **P1** | 6-8h | |
| 7 | Hybrid Retrieval | **P1** | 3-4h | Search quality |
| 8 | Chunk Expansion | **P1** | 2-3h | Context |
| 9 | VAD Timestamps | **P2** | 3h | |
| 10 | Incremental Embeddings | **P2** | 4h | |
| 11 | Adaptive Buffer Sizing | **P2** | 4h | |
| 12 | Frontend Energy Gating | **P2** | 1h | |
| 13 | WebSocket Compression | **P2** | 2h | |
| 14 | Time-Weighted Ranking | **P2** | 1-2h | Recency |
| 15 | LLM Tier Classification | **P2** | 2-3h | Post-demo |

---

# Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-08 | Created optimization backlog | Document future improvements |
| 2026-01-08 | Prioritized as P0/P1/P2 | Quick wins first, then impact |
| 2026-01-08 | Implemented tiered retrieval + grounding | Fixes hallucination issue |
| 2026-01-08 | Skip LLM tier classification | Keyword works for demo, revisit if senior requests |

