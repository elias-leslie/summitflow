-- Migration: 091_add_step_status.sql
-- Purpose: Add status column to task_subtask_steps for plan_defect tracking
-- Created: 2026-01-22
-- Context: QA review loop needs to distinguish between implementation failures
--          and plan defects (where the step's verification was wrong)

-- Add status column to steps
-- Values: 'pending' (default), 'passed', 'failed', 'plan_defect'
ALTER TABLE task_subtask_steps ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'pending';

-- Add fix_subtask_id column to link plan_defect steps to their fix subtasks
-- This enforces that plan_defect steps must have a completed fix subtask
ALTER TABLE task_subtask_steps ADD COLUMN IF NOT EXISTS fix_subtask_id TEXT REFERENCES task_subtasks(id) ON DELETE SET NULL;

-- Add check constraint for valid status values
-- Note: Using DO block to handle constraint already existing
DO $$
BEGIN
    ALTER TABLE task_subtask_steps
    ADD CONSTRAINT task_subtask_steps_status_check
    CHECK (status IN ('pending', 'passed', 'failed', 'plan_defect'));
EXCEPTION
    WHEN duplicate_object THEN
        NULL; -- Constraint already exists
END $$;

-- Migrate existing data: if passes=true, status='passed'
UPDATE task_subtask_steps SET status = 'passed' WHERE passes = TRUE AND status = 'pending';

-- Comments for documentation
COMMENT ON COLUMN task_subtask_steps.status IS 'Step status: pending, passed, failed, or plan_defect (verification was wrong)';
