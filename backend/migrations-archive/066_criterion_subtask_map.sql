-- Migration: 066_criterion_subtask_map.sql
-- Purpose: Map acceptance criteria to subtasks (many-to-many with primary flag)
-- Created: 2026-01-16
-- Task: task-48ae552b (Normalize task schema)

-- Junction table linking criteria to subtasks
-- Enables tracking which subtask(s) implement which criteria
CREATE TABLE IF NOT EXISTS criterion_subtask_map (
    criterion_id INTEGER NOT NULL REFERENCES task_acceptance_criteria(id) ON DELETE CASCADE,
    subtask_id TEXT NOT NULL REFERENCES task_subtasks(id) ON DELETE CASCADE,
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY(criterion_id, subtask_id)
);

-- Indexes for efficient lookups in both directions
CREATE INDEX IF NOT EXISTS idx_criterion_subtask_criterion ON criterion_subtask_map(criterion_id);
CREATE INDEX IF NOT EXISTS idx_criterion_subtask_subtask ON criterion_subtask_map(subtask_id);

COMMENT ON TABLE criterion_subtask_map IS 'Maps criteria to implementing subtasks. is_primary marks the main subtask for a criterion.';
COMMENT ON COLUMN criterion_subtask_map.is_primary IS 'TRUE if this subtask is the primary implementer of the criterion';
