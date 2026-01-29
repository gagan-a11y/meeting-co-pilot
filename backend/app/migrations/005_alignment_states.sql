-- Migration: Alignment State Columns
-- Purpose: Track alignment quality and uncertainty
-- Date: 2026-01-28

-- Add alignment state columns to transcript_segments
ALTER TABLE transcript_segments
  ADD COLUMN IF NOT EXISTS alignment_state TEXT DEFAULT 'CONFIDENT'
    CHECK (alignment_state IN ('CONFIDENT', 'UNCERTAIN', 'OVERLAP', 'UNKNOWN_SPEAKER')),
  ADD COLUMN IF NOT EXISTS alignment_method TEXT,
  ADD COLUMN IF NOT EXISTS speaker_confidence REAL DEFAULT 1.0;

-- Create index for filtering by state
CREATE INDEX IF NOT EXISTS idx_transcript_segments_state
  ON transcript_segments(meeting_id, alignment_state);

-- Create index for confidence queries
CREATE INDEX IF NOT EXISTS idx_transcript_segments_confidence
  ON transcript_segments(meeting_id, speaker_confidence);

-- Add comments for documentation
COMMENT ON COLUMN transcript_segments.alignment_state IS 'Alignment confidence state: CONFIDENT (good), UNCERTAIN (low confidence), OVERLAP (multiple speakers), UNKNOWN_SPEAKER (no speaker detected)';
COMMENT ON COLUMN transcript_segments.alignment_method IS 'Method used for alignment: time_overlap, word_density, uncertain';
COMMENT ON COLUMN transcript_segments.speaker_confidence IS 'Confidence score 0.0-1.0 for speaker attribution';
