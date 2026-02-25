-- Migration: Add CHECK constraint for task_type
-- Ensures only valid task types can be stored

-- Add CHECK constraint for task_type column
ALTER TABLE tasks
ADD CONSTRAINT tasks_task_type_check
CHECK (task_type IN ('feature', 'bug', 'task', 'refactor', 'debt', 'regression'));
