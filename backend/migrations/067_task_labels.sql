-- Migration: 067_task_labels.sql
-- Purpose: Normalize labels from TEXT[] array to junction table
-- Created: 2026-01-16
-- Task: task-48ae552b (Normalize task schema)

-- Task labels junction table (normalizes tasks.labels TEXT[])
CREATE TABLE IF NOT EXISTS task_labels (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY(task_id, label)
);

-- Index for label-based queries (find tasks with specific label)
CREATE INDEX IF NOT EXISTS idx_task_labels_label ON task_labels(label);

COMMENT ON TABLE task_labels IS 'Normalized storage for task labels. Replaces tasks.labels TEXT[].';
