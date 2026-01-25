-- Migration: 094_subtask_summaries.sql
-- Purpose: Create subtask_summaries table for handoff context isolation between subtasks
-- Created: 2026-01-24
-- Rationale: Fresh context per subtask prevents context rot. Each subtask starts with
--            a summary of previous work rather than accumulated context.

CREATE TABLE IF NOT EXISTS subtask_summaries (
    id SERIAL PRIMARY KEY,
    subtask_id TEXT NOT NULL REFERENCES task_subtasks(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    files_modified JSONB DEFAULT '[]'::jsonb,
    decisions_made JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT subtask_summaries_unique_subtask UNIQUE(subtask_id)
);

CREATE INDEX IF NOT EXISTS idx_subtask_summaries_subtask_id ON subtask_summaries(subtask_id);

COMMENT ON TABLE subtask_summaries IS 'Handoff context for subtask-to-subtask transitions. Enables fresh context per subtask.';
COMMENT ON COLUMN subtask_summaries.subtask_id IS 'Reference to task_subtasks.id (e.g., "task-abc123-1.1")';
COMMENT ON COLUMN subtask_summaries.summary IS 'Structured summary of work done, key decisions, and gotchas discovered';
COMMENT ON COLUMN subtask_summaries.files_modified IS 'Array of file paths modified during this subtask';
COMMENT ON COLUMN subtask_summaries.decisions_made IS 'Array of key decisions made during execution';
