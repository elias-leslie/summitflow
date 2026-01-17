-- Migration 077: Add updated_at columns to core tables
-- Part of quality gate infrastructure - enables tracking last modification time

-- Add updated_at to tasks table
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Add updated_at to task_subtasks table
ALTER TABLE task_subtasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Add updated_at to acceptance_criteria table
ALTER TABLE acceptance_criteria ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Backfill updated_at from created_at for existing rows
UPDATE tasks SET updated_at = COALESCE(started_at, created_at) WHERE updated_at IS NULL;
UPDATE task_subtasks SET updated_at = COALESCE(passed_at, created_at) WHERE updated_at IS NULL;
UPDATE acceptance_criteria SET updated_at = created_at WHERE updated_at IS NULL;

-- Create indexes for updated_at columns (commonly used in sorting/filtering)
CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_subtasks_updated ON task_subtasks(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_acceptance_criteria_updated ON acceptance_criteria(updated_at DESC);
