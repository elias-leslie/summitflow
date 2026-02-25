-- Migration 032: Add structured summary columns to session_diary
-- Enables structured session summaries for better context retrieval

-- Add structured summary columns
ALTER TABLE session_diary
ADD COLUMN IF NOT EXISTS summary_request TEXT,
ADD COLUMN IF NOT EXISTS summary_investigated TEXT,
ADD COLUMN IF NOT EXISTS summary_learned TEXT,
ADD COLUMN IF NOT EXISTS summary_completed TEXT,
ADD COLUMN IF NOT EXISTS summary_next_steps TEXT;

COMMENT ON COLUMN session_diary.summary_request IS 'What the user requested (1-2 sentences)';
COMMENT ON COLUMN session_diary.summary_investigated IS 'What was explored/investigated';
COMMENT ON COLUMN session_diary.summary_learned IS 'Key learnings or discoveries';
COMMENT ON COLUMN session_diary.summary_completed IS 'What was accomplished';
COMMENT ON COLUMN session_diary.summary_next_steps IS 'Suggested follow-up actions';
