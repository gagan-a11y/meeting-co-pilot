# Phase 5: Stabilization Implementation Plan (ENHANCED)

**Status:** 🚀 IN PROGRESS
**Timeline:** 2-3 Days (Aggressive Sprint)
**Goal:** Make transcription/diarization predictable, debuggable, and non-destructive

---

## Executive Summary

This plan enhances the original Phase 5 with:
- **Smarter timestamp synchronization** using client-side audio context
- **Granular versioning** that tracks every alignment attempt
- **Probabilistic alignment** with explicit confidence scoring
- **Defensive architecture** that preserves data at every step
- **Observable debugging** through structured logging and state tracking

---

## Part 1: Time & Format Standardization (Day 1 Morning)

### Problem
Current system uses **server arrival time** for timestamps, causing:
- Network jitter (50-200ms variability)
- Drift between live and post-processed transcripts
- Alignment failures when replaying audio

### Solution

#### 1.1 Client-Side Audio Context Timestamps

**File:** `frontend/src/lib/audio-streaming/AudioStreamClient.ts`

**Changes:**
```typescript
class AudioStreamClient {
  private audioContext: AudioContext;
  private recordingStartTime: number = 0; // AudioContext.currentTime at start

  async start() {
    this.audioContext = new AudioContext({ sampleRate: 48000 });
    this.recordingStartTime = this.audioContext.currentTime;

    // In audio processor callback:
    this.sendAudioChunk(pcmData, {
      timestamp: this.audioContext.currentTime - this.recordingStartTime,
      sample_rate: 16000,
      chunk_duration_ms: (pcmData.length / 32000) * 1000
    });
  }
}
```

**Benefits:**
- Sub-millisecond precision (AudioContext is hardware-synced)
- Immune to network delays
- Perfect sync for audio playback later

#### 1.2 Backend Timestamp Standardization

**File:** `backend/app/streaming_transcription.py`

**Current:**
```python
# BEFORE: Uses server time (arrival time)
timestamp = time.time() - self.session_start_time
```

**After:**
```python
# AFTER: Uses client-provided timestamp
async def process_audio_chunk(
    self,
    audio_data: bytes,
    client_timestamp: float,  # NEW: From AudioContext
    ...
):
    # Validate timestamp is monotonic
    if client_timestamp < self.last_chunk_timestamp:
        logger.warning(f"Non-monotonic timestamp: {client_timestamp} < {self.last_chunk_timestamp}")
        client_timestamp = self.last_chunk_timestamp + 0.1

    self.speech_start_time = client_timestamp
    self.speech_end_time = client_timestamp + chunk_duration
```

#### 1.3 Dual Timestamp Storage

**Schema Migration:** `backend/app/migrations/003_dual_timestamps.sql`

```sql
ALTER TABLE transcript_segments
  ADD COLUMN audio_start_time_raw REAL,  -- Raw seconds from recording start
  ADD COLUMN audio_end_time_raw REAL,
  ADD COLUMN formatted_time TEXT;        -- [MM:SS] for UI display

-- Backfill existing data
UPDATE transcript_segments
SET
  audio_start_time_raw = audio_start_time,
  audio_end_time_raw = audio_end_time,
  formatted_time = to_char((audio_start_time || ' seconds')::interval, 'MI:SS');
```

---

## Part 2: Transcript Versioning (Day 1 Afternoon)

### Problem
Current system **overwrites** live transcripts with diarized output:
- No way to compare before/after
- Data loss if diarization fails
- No rollback mechanism

### Solution

#### 2.1 Versioning Schema

**File:** `backend/app/migrations/004_transcript_versions.sql`

```sql
CREATE TABLE IF NOT EXISTS transcript_versions (
  id SERIAL PRIMARY KEY,
  meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  version_num INTEGER NOT NULL,  -- Auto-incremented per meeting
  source TEXT NOT NULL,           -- 'live' | 'diarized' | 'manual_edit'
  content_json JSONB NOT NULL,    -- Array of transcript segments
  is_authoritative BOOLEAN DEFAULT FALSE,

  -- Metadata for debugging
  created_at TIMESTAMP DEFAULT NOW(),
  created_by TEXT,                -- 'system' | user_email
  alignment_config JSONB,         -- Store which alignment algo was used
  confidence_metrics JSONB,       -- Stats: avg_confidence, uncertain_count, etc.

  UNIQUE(meeting_id, version_num)
);

CREATE INDEX idx_transcript_versions_meeting ON transcript_versions(meeting_id);
CREATE INDEX idx_transcript_versions_auth ON transcript_versions(meeting_id, is_authoritative);
```

#### 2.2 Versioning Logic

**File:** `backend/app/db.py`

```python
async def save_transcript_version(
    self,
    meeting_id: str,
    source: str,  # 'live' | 'diarized'
    segments: List[Dict],
    is_authoritative: bool = False,
    metadata: Optional[Dict] = None
) -> int:
    """Save a new transcript version and return version number."""

    # Get next version number
    version_num = await self._get_next_version_num(meeting_id)

    # If making this authoritative, demote previous
    if is_authoritative:
        await conn.execute("""
            UPDATE transcript_versions
            SET is_authoritative = FALSE
            WHERE meeting_id = $1
        """, meeting_id)

    # Insert new version
    await conn.execute("""
        INSERT INTO transcript_versions (
            meeting_id, version_num, source, content_json,
            is_authoritative, alignment_config, confidence_metrics
        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
    """, meeting_id, version_num, source, json.dumps(segments),
         is_authoritative, json.dumps(metadata or {}),
         json.dumps(self._calculate_confidence_metrics(segments)))

    logger.info(f"Saved transcript version {version_num} for {meeting_id} (source={source}, auth={is_authoritative})")
    return version_num
```

#### 2.3 Frontend Version Switcher

**File:** `frontend/src/components/MeetingDetails/TranscriptVersionSelector.tsx`

```typescript
export function TranscriptVersionSelector({ meetingId }: { meetingId: string }) {
  const [versions, setVersions] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);

  // Fetch versions
  useEffect(() => {
    fetch(`/api/meetings/${meetingId}/versions`)
      .then(r => r.json())
      .then(data => {
        setVersions(data.versions);
        // Default to authoritative or latest
        const auth = data.versions.find(v => v.is_authoritative);
        setSelectedVersion(auth?.version_num || data.versions[0]?.version_num);
      });
  }, [meetingId]);

  return (
    <div className="version-selector">
      <label>Transcript Version:</label>
      <select value={selectedVersion} onChange={e => setSelectedVersion(Number(e.target.value))}>
        {versions.map(v => (
          <option key={v.version_num} value={v.version_num}>
            v{v.version_num} - {v.source}
            {v.is_authoritative && ' ⭐ (Active)'}
            - {v.confidence_metrics?.avg_confidence?.toFixed(2) || 'N/A'}
          </option>
        ))}
      </select>
    </div>
  );
}
```

---

## Part 3: Alignment Engine Redesign (Day 2)

### Problem
Current alignment uses **only time overlap**, which fails when:
- Whisper timestamps drift from actual audio
- Speaker changes mid-sentence
- Multiple speakers overlap

### Solution: 3-Tier Alignment with Confidence

**File:** `backend/app/alignment_engine.py` (NEW)

```python
from dataclasses import dataclass
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)

@dataclass
class AlignmentResult:
    speaker: str
    confidence: float  # 0.0 to 1.0
    method: str        # 'time_overlap' | 'word_density' | 'uncertain'
    state: str         # 'CONFIDENT' | 'UNCERTAIN' | 'OVERLAP'

class AlignmentEngine:
    """
    3-Tier alignment strategy:
    1. Time overlap (primary)
    2. Word density (secondary)
    3. Uncertain fallback
    """

    CONFIDENCE_THRESHOLD = 0.6
    OVERLAP_THRESHOLD = 0.5  # 50% time overlap required

    def align_segment(
        self,
        text: str,
        start_time: float,
        end_time: float,
        speaker_segments: List[dict]  # From Deepgram
    ) -> AlignmentResult:
        """
        Align a single transcript segment to speaker labels.

        Returns:
            AlignmentResult with speaker, confidence, method, and state
        """

        # Tier 1: Time Overlap
        time_result = self._align_by_time_overlap(start_time, end_time, speaker_segments)
        if time_result.confidence >= self.CONFIDENCE_THRESHOLD:
            return time_result

        # Tier 2: Word Density (for Whisper timestamp drift)
        density_result = self._align_by_word_density(
            text, start_time, end_time, speaker_segments
        )
        if density_result.confidence >= self.CONFIDENCE_THRESHOLD:
            return density_result

        # Tier 3: Uncertain
        return AlignmentResult(
            speaker="Unknown",
            confidence=max(time_result.confidence, density_result.confidence),
            method="uncertain",
            state="UNCERTAIN"
        )

    def _align_by_time_overlap(
        self,
        start: float,
        end: float,
        speaker_segments: List[dict]
    ) -> AlignmentResult:
        """Primary alignment: Calculate time overlap with each speaker."""

        segment_duration = end - start
        if segment_duration <= 0:
            return AlignmentResult("Unknown", 0.0, "time_overlap", "UNCERTAIN")

        speaker_overlaps = {}
        total_overlap = 0.0

        for seg in speaker_segments:
            overlap_start = max(start, seg['start_time'])
            overlap_end = min(end, seg['end_time'])

            if overlap_end > overlap_start:
                overlap_duration = overlap_end - overlap_start
                speaker_overlaps[seg['speaker']] = overlap_duration
                total_overlap += overlap_duration

        if not speaker_overlaps:
            return AlignmentResult("Unknown", 0.0, "time_overlap", "UNCERTAIN")

        # Find best speaker
        best_speaker = max(speaker_overlaps, key=speaker_overlaps.get)
        best_overlap = speaker_overlaps[best_speaker]

        # Calculate confidence
        overlap_ratio = best_overlap / segment_duration
        confidence = min(overlap_ratio / self.OVERLAP_THRESHOLD, 1.0)

        # Check for overlap (multiple speakers speaking)
        if len([s for s, o in speaker_overlaps.items() if o > 0.3 * segment_duration]) > 1:
            state = "OVERLAP"
        else:
            state = "CONFIDENT" if confidence >= self.CONFIDENCE_THRESHOLD else "UNCERTAIN"

        logger.debug(
            f"Time alignment: {best_speaker} ({overlap_ratio:.2%} overlap, "
            f"confidence={confidence:.2f}, state={state})"
        )

        return AlignmentResult(best_speaker, confidence, "time_overlap", state)

    def _align_by_word_density(
        self,
        text: str,
        start: float,
        end: float,
        speaker_segments: List[dict]
    ) -> AlignmentResult:
        """
        Secondary alignment: Count words inside each speaker's time window.

        This handles cases where Whisper timestamps drift but the bulk of
        words fall within a speaker's segment.
        """

        words = text.split()
        if len(words) == 0:
            return AlignmentResult("Unknown", 0.0, "word_density", "UNCERTAIN")

        # Estimate word timing (uniform distribution for simplicity)
        duration = end - start
        word_duration = duration / len(words)

        speaker_word_counts = {}

        for i, word in enumerate(words):
            word_start = start + i * word_duration
            word_end = word_start + word_duration
            word_mid = (word_start + word_end) / 2

            # Find which speaker(s) this word overlaps with
            for seg in speaker_segments:
                if seg['start_time'] <= word_mid <= seg['end_time']:
                    speaker_word_counts[seg['speaker']] = speaker_word_counts.get(seg['speaker'], 0) + 1

        if not speaker_word_counts:
            return AlignmentResult("Unknown", 0.0, "word_density", "UNCERTAIN")

        best_speaker = max(speaker_word_counts, key=speaker_word_counts.get)
        words_in_speaker = speaker_word_counts[best_speaker]

        # Confidence based on percentage of words in best speaker's window
        confidence = words_in_speaker / len(words)
        state = "CONFIDENT" if confidence >= 0.7 else "UNCERTAIN"

        logger.debug(
            f"Word density alignment: {best_speaker} "
            f"({words_in_speaker}/{len(words)} words, confidence={confidence:.2f})"
        )

        return AlignmentResult(best_speaker, confidence, "word_density", state)
```

#### 3.2 Integration with Diarization Service

**File:** `backend/app/diarization.py`

```python
from alignment_engine import AlignmentEngine

class DiarizationService:
    def __init__(self, ...):
        self.alignment_engine = AlignmentEngine()

    async def align_with_transcripts(
        self,
        meeting_id: str,
        diarization_result: DiarizationResult,
        transcripts: List[Dict]
    ) -> Tuple[List[Dict], Dict]:
        """
        Returns: (aligned_transcripts, metrics)
        """

        aligned = []
        metrics = {
            'total_segments': len(transcripts),
            'confident_count': 0,
            'uncertain_count': 0,
            'overlap_count': 0,
            'avg_confidence': 0.0,
            'method_breakdown': {}
        }

        for transcript in transcripts:
            start = transcript.get('audio_start_time', 0)
            end = transcript.get('audio_end_time', start + 2)
            text = transcript.get('text', '')

            # Run alignment
            result = self.alignment_engine.align_segment(
                text, start, end, diarization_result.segments
            )

            # Track metrics
            metrics['method_breakdown'][result.method] = metrics['method_breakdown'].get(result.method, 0) + 1
            if result.state == 'CONFIDENT':
                metrics['confident_count'] += 1
            elif result.state == 'UNCERTAIN':
                metrics['uncertain_count'] += 1
            elif result.state == 'OVERLAP':
                metrics['overlap_count'] += 1

            metrics['avg_confidence'] += result.confidence

            # Add to aligned transcripts
            aligned.append({
                **transcript,
                'speaker': result.speaker,
                'speaker_confidence': result.confidence,
                'alignment_method': result.method,
                'alignment_state': result.state
            })

        # Finalize metrics
        metrics['avg_confidence'] /= len(transcripts) if transcripts else 1

        logger.info(
            f"Alignment complete: {metrics['confident_count']}/{metrics['total_segments']} confident, "
            f"{metrics['uncertain_count']} uncertain, {metrics['overlap_count']} overlap"
        )

        return aligned, metrics
```

---

## Part 4: Confidence & State Modeling (Day 2 Afternoon)

### Schema Update

**File:** `backend/app/migrations/005_confidence_states.sql`

```sql
ALTER TABLE transcript_segments
  ADD COLUMN alignment_state TEXT DEFAULT 'CONFIDENT',  -- CONFIDENT | UNCERTAIN | OVERLAP | UNKNOWN_SPEAKER
  ADD COLUMN alignment_method TEXT,                     -- time_overlap | word_density | uncertain
  ADD COLUMN speaker_confidence REAL DEFAULT 1.0;       -- 0.0 to 1.0

-- Create index for filtering by state
CREATE INDEX idx_transcript_segments_state ON transcript_segments(alignment_state);
```

### Frontend Display

**File:** `frontend/src/components/TranscriptView.tsx`

```typescript
function TranscriptSegment({ segment }: { segment: TranscriptSegment }) {
  const getStateStyle = (state: string) => {
    switch (state) {
      case 'CONFIDENT':
        return 'border-green-500';
      case 'UNCERTAIN':
        return 'border-yellow-500 bg-yellow-50';
      case 'OVERLAP':
        return 'border-orange-500 bg-orange-50';
      default:
        return 'border-gray-300';
    }
  };

  return (
    <div className={`transcript-segment ${getStateStyle(segment.alignment_state)}`}>
      <div className="speaker-label">
        {segment.speaker}
        {segment.alignment_state === 'UNCERTAIN' && (
          <span className="uncertainty-badge" title={`Confidence: ${(segment.speaker_confidence * 100).toFixed(0)}%`}>
            ?
          </span>
        )}
        {segment.alignment_state === 'OVERLAP' && (
          <span className="overlap-badge" title="Multiple speakers detected">
            ⚠️
          </span>
        )}
      </div>
      <div className="text">{segment.text}</div>
      {/* Debug info (only in dev mode) */}
      {process.env.NODE_ENV === 'development' && (
        <div className="debug-info text-xs text-gray-500">
          Method: {segment.alignment_method} |
          Confidence: {(segment.speaker_confidence * 100).toFixed(0)}%
        </div>
      )}
    </div>
  );
}
```

---

## Part 5: Connection Robustness (Day 3)

### WebSocket Heartbeat

**File:** `backend/app/main.py`

```python
@app.websocket("/ws/streaming-audio")
async def streaming_audio_websocket(websocket: WebSocket):
    await websocket.accept()

    session_id = str(uuid.uuid4())
    last_heartbeat = time.time()
    HEARTBEAT_TIMEOUT = 15.0  # seconds

    # Start heartbeat monitor
    async def heartbeat_monitor():
        while True:
            await asyncio.sleep(5)
            if time.time() - last_heartbeat > HEARTBEAT_TIMEOUT:
                logger.warning(f"Session {session_id}: Heartbeat timeout, closing")
                await force_flush_and_close(session_id)
                await websocket.close()
                break

    monitor_task = asyncio.create_task(heartbeat_monitor())

    try:
        async for message in websocket.iter_json():
            if message.get('type') == 'ping':
                last_heartbeat = time.time()
                await websocket.send_json({'type': 'pong'})
            elif message.get('type') == 'audio':
                # Process audio
                await manager.process_audio_chunk(...)
    finally:
        monitor_task.cancel()
        await force_flush_and_close(session_id)
```

**File:** `frontend/src/lib/audio-streaming/AudioStreamClient.ts`

```typescript
class AudioStreamClient {
  private heartbeatInterval: NodeJS.Timeout | null = null;

  start() {
    // Start heartbeat every 5 seconds
    this.heartbeatInterval = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 5000);
  }

  stop() {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }
}
```

### Graceful Disconnect Flush

**File:** `backend/app/streaming_transcription.py`

```python
async def force_flush(self):
    """
    Flush any pending audio in the buffer and finalize partial transcripts.
    Called on disconnect or manual stop.
    """
    logger.info("🚨 Force flush triggered")

    # Get remaining audio
    remaining_bytes = self.buffer.get_all_samples_bytes()

    if len(remaining_bytes) > 16000:  # At least 0.5s of audio
        logger.info(f"Flushing {len(remaining_bytes)} bytes of remaining audio")

        # Transcribe final chunk
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self.executor,
            self.groq.transcribe_audio_sync,
            remaining_bytes,
            "auto",
            self.last_final_text[-100:] if self.last_final_text else None,
            True
        )

        if result['text']:
            logger.info(f"✅ Flushed final segment: '{result['text'][:50]}...'")
            # Emit as final
            return {
                'text': result['text'],
                'confidence': result.get('confidence', 1.0),
                'is_flush': True
            }

    return None
```

---

## Success Metrics (Exit Criteria)

### Quantitative Metrics

1. **Zero Data Loss**
   ```python
   # Test: Compare word count between live and diarized versions
   live_words = sum(len(t['text'].split()) for t in live_version)
   diarized_words = sum(len(t['text'].split()) for t in diarized_version)
   loss_percentage = abs(live_words - diarized_words) / live_words * 100
   assert loss_percentage < 5%, f"Data loss: {loss_percentage:.1f}%"
   ```

2. **Attribution Integrity**
   ```python
   # Test: 95% of segments are confident or explicitly uncertain
   total = len(segments)
   confident = sum(1 for s in segments if s['alignment_state'] in ['CONFIDENT', 'UNCERTAIN', 'OVERLAP'])
   integrity = confident / total * 100
   assert integrity >= 95%, f"Attribution integrity: {integrity:.1f}%"
   ```

3. **Timestamp Accuracy**
   ```python
   # Test: Audio playback sync within 500ms
   for segment in segments:
       actual_audio_time = get_audio_position_at_word(segment['text'])
       recorded_time = segment['audio_start_time']
       drift = abs(actual_audio_time - recorded_time)
       assert drift <= 0.5, f"Drift: {drift:.2f}s"
   ```

### Qualitative Metrics

1. **Debuggability**
   - Every alignment decision logged with reason
   - Transcript versions show before/after comparison
   - Confidence metrics visible in UI (dev mode)

2. **User Trust**
   - No silent data replacement (version selector visible)
   - Uncertainty explicitly communicated
   - Rollback available via version history

---

## Implementation Checklist

### Day 1 (Timestamps + Versioning)
- [ ] Client-side AudioContext timestamping
- [ ] Backend accepts `client_timestamp` parameter
- [ ] Dual timestamp storage migration
- [ ] Transcript versioning schema
- [ ] `save_transcript_version()` function
- [ ] Basic version API endpoint

### Day 2 (Alignment + State Modeling)
- [ ] `alignment_engine.py` with 3-tier logic
- [ ] Integration with diarization service
- [ ] Confidence metrics calculation
- [ ] State schema migration (CONFIDENT/UNCERTAIN/OVERLAP)
- [ ] Updated diarization endpoint

### Day 3 (Robustness + UI)
- [ ] WebSocket heartbeat (backend)
- [ ] Heartbeat ping (frontend)
- [ ] Force flush on disconnect
- [ ] Frontend state visualization
- [ ] Version selector UI component
- [ ] Quick integration testing

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Alignment still fails in chaotic meetings | Medium | Prefer UNCERTAIN over forced attribution, allow manual editing |
| Hinglish tokenization mismatch | Medium | Word density algorithm is whitespace-agnostic |
| Developer confusion during migration | Low | Clear versioning, authoritative flag, documentation |
| User trust issues | High | Never silently replace, show version history, explicit uncertainty |
| Performance degradation | Medium | Alignment runs async post-meeting, no real-time impact |

---

## Open Questions (Deferred to Phase 6)

1. **When should diarized transcripts auto-replace live ones in UI?**
   - Proposal: Show diarized by default only if `avg_confidence >= 0.75`

2. **How should UNCERTAIN segments be visualized?**
   - Proposal: Yellow background + question mark badge

3. **Speaker identity persistence across meetings?**
   - Phase 6: Voice fingerprinting + user enrollment

---

## Conclusion

This enhanced Phase 5 plan delivers:

✅ **Non-Destructive:** Versioning prevents data loss
✅ **Debuggable:** Every decision is logged and explainable
✅ **Honest:** Uncertainty is explicit, not hidden
✅ **Accurate:** 3-tier alignment maximizes correct attribution
✅ **Robust:** Heartbeat + flush prevents silent failures

Once complete, the system will be production-ready and trustworthy for critical meeting transcription.
