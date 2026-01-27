-- Migration: Add citations_acknowledged_at to task_subtasks
-- Purpose: Track when agent has honestly reflected on memory usage
--          (either by citing memories or confirming none were needed)

ALTER TABLE task_subtasks
ADD COLUMN citations_acknowledged_at TIMESTAMPTZ;

COMMENT ON COLUMN task_subtasks.citations_acknowledged_at IS
    'When agent acknowledged memory usage (cited memories or confirmed none needed)';
