-- Migration 005: Add issue tracking fields to tasks table
-- Migrating from beads to SummitFlow Tasks system

-- Add issue tracking columns to tasks table
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 2;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS labels TEXT[] DEFAULT '{}';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_type VARCHAR(20) DEFAULT 'task';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS parent_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL;

-- Add indexes for new columns
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);

-- Create task_dependencies table for dependency tracking
CREATE TABLE IF NOT EXISTS task_dependencies (
    id SERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on_task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    dependency_type VARCHAR(20) NOT NULL,  -- 'blocks', 'discovered-from'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(task_id, depends_on_task_id, dependency_type)
);

CREATE INDEX IF NOT EXISTS idx_task_deps_task ON task_dependencies(task_id);
CREATE INDEX IF NOT EXISTS idx_task_deps_depends ON task_dependencies(depends_on_task_id);

-- Add comments for documentation
COMMENT ON COLUMN tasks.priority IS 'Priority 0-4 scale: 0=critical, 1=high, 2=medium (default), 3=low, 4=backlog';
COMMENT ON COLUMN tasks.labels IS 'Array of labels: complexity:small|medium|large, domains:backend|frontend|database';
COMMENT ON COLUMN tasks.task_type IS 'Type: task, bug, chore';
COMMENT ON COLUMN tasks.parent_task_id IS 'Parent task ID for hierarchical subtasks';
COMMENT ON TABLE task_dependencies IS 'Dependency relationships between tasks';
COMMENT ON COLUMN task_dependencies.dependency_type IS 'Type: blocks (must complete first), discovered-from (found during work)';
