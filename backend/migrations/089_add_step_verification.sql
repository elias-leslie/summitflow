-- Migration: 089_add_step_verification.sql
-- Purpose: Add verification fields to steps for tight agent feedback loop
-- Created: 2026-01-21
-- Context: Moving verification from task-level criteria to step-level
--          Enables: code → verify → fix if fail → repeat loop

-- Add verification columns to steps
ALTER TABLE task_subtask_steps ADD COLUMN IF NOT EXISTS verify_command TEXT;
ALTER TABLE task_subtask_steps ADD COLUMN IF NOT EXISTS expected_output TEXT;

-- Comments for documentation
COMMENT ON COLUMN task_subtask_steps.verify_command IS 'Bash command to verify step completion (e.g., pytest, curl, grep)';
COMMENT ON COLUMN task_subtask_steps.expected_output IS 'Expected output pattern or description for verification';
