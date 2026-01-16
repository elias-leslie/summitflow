-- Migration: 071_data_migration_labels.sql
-- Purpose: Extract tasks.labels array -> task_labels rows
-- Created: 2026-01-16
-- Task: task-48ae552b (Normalize task schema)
--
-- Source: 412 tasks with labels

-- =============================================================================
-- Step 5: Extract labels from tasks.labels array to task_labels table
-- =============================================================================

-- Use unnest to expand arrays into rows
INSERT INTO task_labels (task_id, label)
SELECT
    id as task_id,
    unnest(labels) as label
FROM tasks
WHERE labels IS NOT NULL AND array_length(labels, 1) > 0
ON CONFLICT (task_id, label) DO NOTHING;
