-- Migration 101: Add agent_override column to tasks table
-- Allows manual override of which agent executes the task

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS agent_override VARCHAR(50);

-- Comment explaining the column
COMMENT ON COLUMN tasks.agent_override IS 'Manual override of agent slug for task execution. If set, uses this agent instead of task_type default.';
