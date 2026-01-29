-- Migration: Dual Timestamp Format
-- Purpose: Store both raw seconds and formatted time for precise audio sync
-- Date: 2026-01-28

-- Add dual timestamp columns
ALTER TABLE transcript_segments
  ADD COLUMN IF NOT EXISTS audio_start_time_raw REAL,
  ADD COLUMN IF NOT EXISTS audio_end_time_raw REAL,
  ADD COLUMN IF NOT EXISTS formatted_time TEXT;

-- Backfill existing data (if any)
UPDATE transcript_segments
SET
  audio_start_time_raw = COALESCE(audio_start_time, 0),
  audio_end_time_raw = COALESCE(audio_end_time, 0),
  formatted_time = CASE
    WHEN audio_start_time IS NOT NULL THEN
      LPAD(FLOOR(audio_start_time / 60.0)::INTEGER::TEXT, 2, '0') || ':' ||
      LPAD(FLOOR(audio_start_time::NUMERIC % 60)::INTEGER::TEXT, 2, '0')
    ELSE '[00:00]'
  END
WHERE audio_start_time_raw IS NULL;

-- Create index for time-based queries
CREATE INDEX IF NOT EXISTS idx_transcript_segments_time_range
  ON transcript_segments(meeting_id, audio_start_time_raw, audio_end_time_raw);

-- Add comment for documentation
COMMENT ON COLUMN transcript_segments.audio_start_time_raw IS 'Raw offset in seconds from recording start (client AudioContext time)';
COMMENT ON COLUMN transcript_segments.audio_end_time_raw IS 'Raw offset in seconds from recording start (client AudioContext time)';
COMMENT ON COLUMN transcript_segments.formatted_time IS 'Human-readable timestamp [MM:SS] for UI display';
