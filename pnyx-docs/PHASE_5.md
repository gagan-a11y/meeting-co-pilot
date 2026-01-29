# Phase 5: Diarization & Transcription Stabilization Plan (PNYX)

**Status:** 🚀 READY FOR EXECUTION  
**Owner:** Engineering  
**Timeline:** 2–3 Weeks  
**Primary Goal:** Stabilization, not feature expansion

---

## 1. Purpose

Phase 5 focuses exclusively on making the existing transcription and diarization pipeline **predictable, debuggable, and non-destructive**.

This phase intentionally pauses all new feature development.  
The objective is to eliminate data loss, timestamp drift, and speaker misattribution during the transition from **Live Transcription** to **Post-Meeting Diarization**.

Success is defined by **trustworthiness**, not perfection.

---

## 2. Non-Goals (Explicit)

This phase does NOT aim to:
- Achieve perfect real-time diarization
- Eliminate all speaker uncertainty
- Introduce new vendors or models
- Improve UI/UX beyond correctness indicators
- Optimize for cost or performance beyond current baselines

---

## 3. Current Problems (As-Is)

### Observed Issues
- Live transcripts are overwritten by post-processed diarized output
- Timestamp drift between live and post pipelines
- Misalignment between Whisper text and diarization speaker segments
- Text disappearing when diarization alignment fails
- Difficult debugging due to lack of transcript versioning
- Forced speaker attribution even when confidence is low

### Root Causes
- Over-trust in Whisper timestamps and sentence boundaries
- Treating diarization as deterministic instead of probabilistic
- No explicit uncertainty or overlap states
- Alignment logic assumes clean, non-overlapping speech
- Multiple VADs influencing flow without a single authority

---

## 4. Core Design Principles (Going Forward)

1. **Live ≠ Final**
   - Live transcription is fast, approximate, and disposable.
   - Post-meeting output is slower, probabilistic, and authoritative.

2. **Never Destroy Data**
   - No transcript is ever deleted or overwritten.
   - All improvements are versioned.

3. **Silence is Better Than Wrong Attribution**
   - Unknown or uncertain speaker is acceptable.
   - Confidently wrong attribution is not.

4. **Confidence Over Completeness**
   - Every segment must carry confidence or state.
   - UI and downstream logic must respect uncertainty.

5. **Everything Must Be Debuggable**
   - Alignment decisions must be explainable.
   - Failure states must be observable.

---

## 5. Phase 5 Execution Plan

### Step 1: Time & Format Standardization (Week 1)

**Goal:** Ensure all system components speak the same time language.

#### Actions
- Enforce dual timestamp format everywhere:
  - `formatted_time`: `[MM:SS]`
  - `raw_time`: `seconds (float)`
- Update backend schema and frontend rendering to use the same source of truth.
- Shift timestamp authority to the **client**:
  - Frontend sends `audio_start_time` relative to recording start with every audio chunk.
  - Backend uses this instead of arrival time to avoid network jitter.

---

### Step 2: Transcript Versioning (Week 1–1.5)

**Goal:** Prevent data loss and enable safe refinement.

#### Schema Changes
- Introduce `transcript_versions` table:
  - `id`
  - `meeting_id`
  - `source`: `live | diarized`
  - `content_json`
  - `is_authoritative`
  - `created_at`

#### Rules
- Live transcription always writes to `source = live`.
- Diarized output creates a new version (`source = diarized`).
- Live transcript is never deleted.
- Diarized transcript becomes authoritative **only after passing success metrics**.
- UI must be able to toggle between versions.

---

### Step 3: Alignment Engine Redesign (Week 2)

**Goal:** Make alignment robust to drift, overlap, and noise.

#### Alignment Strategy (3-Tier)

1. **Primary: Time Overlap**
   - Assign speaker if overlap between text segment and diarization segment ≥ 60%.

2. **Secondary: Word Density**
   - Count number of Whisper words inside each speaker window.
   - Assign speaker with highest word density.

3. **Fallback: Uncertain**
   - If no speaker crosses confidence threshold:
     - Preserve text.
     - Mark segment as `UNCERTAIN`.
     - Do NOT guess.

#### Constraints
- Levenshtein / fuzzy string matching is allowed ONLY when:
  - Segment length < 6 words
  - Same language block
  - Timestamp proximity < 500ms
- It must never be the primary alignment mechanism.

---

### Step 4: Confidence & State Modeling (Week 2)

**Goal:** Make uncertainty explicit and first-class.

#### New Internal Segment States
- `CONFIDENT`
- `UNCERTAIN`
- `OVERLAP`
- `UNKNOWN_SPEAKER`

These states are internal truth markers and must be stored in DB.
UI may surface them later but must respect them immediately.

---

### Step 5: Connection Robustness (Week 2.5)

**Goal:** Prevent silent failures and data truncation.

#### Actions
- Implement WebSocket heartbeat:
  - Client sends `ping` every 5 seconds.
  - Backend closes connection after 15 seconds of silence.
- On disconnect:
  - Force-flush rolling audio buffer.
  - Commit any pending transcription segments.

---

## 6. Success Metrics (Exit Criteria)

Phase 5 is considered complete when:

1. **Zero Data Loss**
   - Total word count difference between live and diarized transcripts < 5%.

2. **Attribution Integrity**
   - ≥ 95% of segments are either:
     - Confidently attributed OR
     - Explicitly marked as `UNCERTAIN` / `OVERLAP`.

3. **Timestamp Accuracy**
   - Audio playback and text highlight drift ≤ 0.5 seconds.

4. **Debuggability**
   - Every diarized segment can explain:
     - Why this speaker was chosen
     - Or why it was marked uncertain

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|----|----|
Alignment still fails in chaotic meetings | Prefer UNCERTAIN over forced attribution |
Hinglish tokenization mismatch | Rely on time + density, not string equality |
Developer confusion during transition | Clear versioning + authoritative flag |
User trust issues | Never silently replace transcripts |

---

## 8. Open Questions (Intentionally Deferred)

- When should diarized transcripts auto-replace live ones in UI?
- How should UNCERTAIN segments be visualized?
- When to introduce speaker identity persistence across meetings?

These are postponed until Phase 6.

---

## 9. Execution Checklist

- [ ] Client-side timestamping implemented
- [ ] Transcript versioning schema deployed
- [ ] Alignment engine rewritten with 3-tier logic
- [ ] UNCERTAIN / OVERLAP states supported end-to-end
- [ ] Heartbeat + graceful disconnect tested
- [ ] Success metrics validated on real meetings

---

## Final Note

This phase is about **earning trust through correctness**, not adding intelligence.

Once Phase 5 is complete, the system will be stable enough to safely evolve.
