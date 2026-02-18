-- Add ai_review flag to tasks table
-- Controls whether st done runs AI review before completion
-- Default TRUE preserves existing behavior; refactor tasks set FALSE at creation

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ai_review BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN tasks.ai_review IS 'Whether to run AI review before task completion. Set FALSE for mechanical tasks like refactors.';
