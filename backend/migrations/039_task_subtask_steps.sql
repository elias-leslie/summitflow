-- Migration: 039_task_subtask_steps.sql
-- Purpose: Normalize steps from JSONB array to dedicated table with individual pass tracking
-- Created: 2026-01-01

-- Steps table - each step is individually tracked for pass/fail
-- Forces AI agents to explicitly mark each step complete via API
CREATE TABLE IF NOT EXISTS task_subtask_steps (
    id SERIAL PRIMARY KEY,
    subtask_id TEXT NOT NULL REFERENCES task_subtasks(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,            -- 1-indexed step within subtask
    description TEXT NOT NULL,
    passes BOOLEAN DEFAULT FALSE,
    passed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT task_subtask_steps_unique UNIQUE(subtask_id, step_number)
);

-- Index for efficient lookup of steps for a subtask
CREATE INDEX IF NOT EXISTS idx_task_subtask_steps_subtask_id ON task_subtask_steps(subtask_id);
CREATE INDEX IF NOT EXISTS idx_task_subtask_steps_passes ON task_subtask_steps(passes);

-- Comments for documentation
COMMENT ON TABLE task_subtask_steps IS 'Normalized storage for individual steps within subtasks. Enables granular completion tracking.';
COMMENT ON COLUMN task_subtask_steps.step_number IS '1-indexed step number within the subtask';
COMMENT ON COLUMN task_subtask_steps.passes IS 'True when step has been completed and verified';
COMMENT ON COLUMN task_subtask_steps.passed_at IS 'Timestamp when step was marked as passing';
