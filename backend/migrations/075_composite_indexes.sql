-- Migration: 075_composite_indexes.sql
-- Purpose: Add composite indexes for common query patterns (PERF-002, PERF-004)
-- Created: 2026-01-16

-- Composite index for filtering tasks by project and status (common in st ready, st list)
CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status);

-- Composite index for sorting tasks by project and created_at (common in task listings)
CREATE INDEX IF NOT EXISTS idx_tasks_project_created ON tasks(project_id, created_at DESC);

-- Composite index for subtask lookups by task and pass status
CREATE INDEX IF NOT EXISTS idx_task_subtasks_task_passes ON task_subtasks(task_id, passes);

-- Comment for documentation
COMMENT ON INDEX idx_tasks_project_status IS 'Composite index for common project+status filter pattern';
COMMENT ON INDEX idx_tasks_project_created IS 'Composite index for project+created_at sort pattern';
COMMENT ON INDEX idx_task_subtasks_task_passes IS 'Composite index for subtask lookups by task and completion status';
