-- Migration 079: Add execution tracking columns to task_subtasks
-- Tracks attempt count and last attempt time for agent execution

-- Add attempt_count to track how many times agent has attempted this subtask
ALTER TABLE task_subtasks ADD COLUMN IF NOT EXISTS attempt_count INTEGER DEFAULT 0;

-- Add last_attempt_at to track when the last attempt occurred
ALTER TABLE task_subtasks ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ;

-- Index for finding subtasks with many attempts (potential blockers)
CREATE INDEX IF NOT EXISTS idx_task_subtasks_attempts ON task_subtasks(attempt_count DESC)
    WHERE attempt_count > 0;
