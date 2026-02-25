-- Migration: 045_drop_subtask_steps_jsonb.sql
-- Description: Drop deprecated steps JSONB column from task_subtasks table
-- Part of Unified nested task creation (task-9ca827ca)
--
-- Steps are now stored exclusively in the normalized task_subtask_steps table.
-- The JSONB column was redundant and caused dual storage issues.

-- Drop the deprecated column
ALTER TABLE task_subtasks DROP COLUMN IF EXISTS steps;

-- Update the column comment for clarity (column is already in use)
COMMENT ON TABLE task_subtask_steps IS 'Normalized step storage for subtasks (replaced task_subtasks.steps JSONB)';

-- Rollback:
-- ALTER TABLE task_subtasks ADD COLUMN steps JSONB DEFAULT '[]'::jsonb;
-- COMMENT ON COLUMN task_subtasks.steps IS 'DEPRECATED: Steps migrated to task_subtask_steps table';
