-- Migration 019: Add approval/rejection counts to learned_patterns
-- Purpose: Track explicit user feedback for retrieval ranking boost

ALTER TABLE learned_patterns ADD COLUMN IF NOT EXISTS approval_count INTEGER DEFAULT 0;
ALTER TABLE learned_patterns ADD COLUMN IF NOT EXISTS rejection_count INTEGER DEFAULT 0;

-- Index for feedback-based queries
CREATE INDEX IF NOT EXISTS idx_learned_patterns_feedback
ON learned_patterns(project_id, approval_count DESC, rejection_count);

COMMENT ON COLUMN learned_patterns.approval_count IS 'Number of times pattern was explicitly approved/upvoted';
COMMENT ON COLUMN learned_patterns.rejection_count IS 'Number of times pattern was explicitly rejected/downvoted';
