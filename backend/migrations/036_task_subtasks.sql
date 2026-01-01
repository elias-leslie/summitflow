-- Migration: 036_task_subtasks.sql
-- Purpose: Create normalized task_subtasks table for structured subtask tracking
-- Created: 2025-12-31

-- Task subtasks table - normalized storage for implementation subtasks
-- Previously stored in plan_content JSONB, now first-class entities
CREATE TABLE IF NOT EXISTS task_subtasks (
    id TEXT PRIMARY KEY,                    -- "task-abc123-1.1" format
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    subtask_id TEXT NOT NULL,               -- "1.1", "1.2", "2.1" etc.
    phase TEXT,                             -- "research", "database", "backend", "frontend", "testing"
    description TEXT NOT NULL,
    steps JSONB DEFAULT '[]'::jsonb,        -- Array of step strings
    passes BOOLEAN DEFAULT FALSE,
    passed_at TIMESTAMP WITH TIME ZONE,
    display_order INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT task_subtasks_unique_subtask UNIQUE(task_id, subtask_id)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_task_subtasks_task_id ON task_subtasks(task_id);
CREATE INDEX IF NOT EXISTS idx_task_subtasks_passes ON task_subtasks(passes);
CREATE INDEX IF NOT EXISTS idx_task_subtasks_phase ON task_subtasks(phase);

-- Comment for documentation
COMMENT ON TABLE task_subtasks IS 'Normalized storage for task implementation subtasks. Each subtask has ordered steps and pass/fail tracking.';
COMMENT ON COLUMN task_subtasks.subtask_id IS 'Hierarchical ID like "1.1", "2.3" representing phase.task order';
COMMENT ON COLUMN task_subtasks.phase IS 'Implementation phase: research, database, backend, frontend, testing';
COMMENT ON COLUMN task_subtasks.steps IS 'JSONB array of step strings to complete this subtask';
