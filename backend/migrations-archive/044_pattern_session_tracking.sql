-- Migration: 044_pattern_session_tracking.sql
-- Description: Add last_used_session_id to learned_patterns for tracking which sessions use patterns
-- Part of Memory Effectiveness Measurement (task-e975adf2)

-- Add column for tracking last session that used the pattern
ALTER TABLE learned_patterns
ADD COLUMN IF NOT EXISTS last_used_session_id TEXT;

-- Index for querying patterns by session
CREATE INDEX IF NOT EXISTS idx_learned_patterns_session
ON learned_patterns(last_used_session_id)
WHERE last_used_session_id IS NOT NULL;

COMMENT ON COLUMN learned_patterns.last_used_session_id IS 'Session ID that last used this pattern';
