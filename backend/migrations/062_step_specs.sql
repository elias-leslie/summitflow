-- Migration: 062_step_specs.sql
-- Purpose: Add spec JSONB column to task_subtask_steps for step-level implementation details
-- Created: 2026-01-15

-- Add spec column for storing step implementation details (API specs, file specs, etc.)
ALTER TABLE task_subtask_steps ADD COLUMN IF NOT EXISTS spec JSONB;

-- Comment for documentation
COMMENT ON COLUMN task_subtask_steps.spec IS 'JSONB for step implementation specs: API details, file operations, prompts, etc.';
