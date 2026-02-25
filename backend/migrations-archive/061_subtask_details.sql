-- Migration: 061_subtask_details.sql
-- Purpose: Add details JSONB column to store rich implementation specifications
-- Created: 2026-01-15

-- Add details column for implementation specs from plan.json
-- This stores the rich "details" object from implementation_plan.subtasks
-- which contains HOW to implement each step (API endpoints, schemas, etc.)
ALTER TABLE task_subtasks ADD COLUMN IF NOT EXISTS details JSONB;

-- Comment for documentation
COMMENT ON COLUMN task_subtasks.details IS 'Rich implementation spec from plan.json - contains HOW to implement (API calls, schemas, triggers)';
