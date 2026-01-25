-- Migration: 096_add_autonomous_statuses.sql
-- Purpose: Add missing statuses for autonomous execution pipeline
-- Created: 2026-01-24
-- Rationale: Add queue, pr_created, human_review to the tasks_status_check constraint
--            These are needed for the autonomous execution engine flow

-- Drop the old check constraint
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;

-- Add the new check constraint with all statuses
ALTER TABLE tasks ADD CONSTRAINT tasks_status_check CHECK (
    status = ANY (ARRAY[
        'pending'::text,
        'queue'::text,
        'ready'::text,
        'running'::text,
        'paused'::text,
        'blocked'::text,
        'pr_created'::text,
        'ai_reviewing'::text,
        'human_review'::text,
        'needs_review'::text,
        'human_reviewing'::text,
        'completed'::text,
        'cancelled'::text,
        'failed'::text
    ])
);

COMMENT ON COLUMN tasks.status IS 'Task status: pending, queue, ready, running, paused, blocked, pr_created, ai_reviewing, human_review, needs_review, human_reviewing, completed, cancelled, failed';
