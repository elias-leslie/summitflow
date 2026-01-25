-- Migration: 095_add_queue_status.sql
-- Purpose: Add 'queue' status for autonomous execution pipeline
-- Created: 2026-01-24
-- Rationale: Tasks flow pending → queue → running. Queue status allows tasks
--            to be queued for autonomous execution with conflict detection.

-- Note: PostgreSQL doesn't have ALTER TYPE ADD VALUE IF NOT EXISTS before v12
-- So we need to handle the case where it may already exist

DO $$
BEGIN
    -- Check if 'queue' value already exists in task_status enum
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumlabel = 'queue'
        AND enumtypid = 'task_status'::regtype
    ) THEN
        ALTER TYPE task_status ADD VALUE 'queue' AFTER 'pending';
    END IF;
END $$;

COMMENT ON TYPE task_status IS 'Task status enum: pending, queue, running, paused, blocked, failed, pr_created, ai_reviewing, human_review, needs_review, human_reviewing, completed, cancelled';
