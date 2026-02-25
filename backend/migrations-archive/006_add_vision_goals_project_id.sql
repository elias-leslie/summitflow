-- Migration 006: Add project_id to vision_goals table
-- Enables scoping vision goals per project (SummitFlow, Portfolio-AI, Context Hub)

-- Add project_id column (nullable initially for existing data)
ALTER TABLE vision_goals ADD COLUMN IF NOT EXISTS project_id TEXT REFERENCES projects(id);

-- Add index for project-scoped queries
CREATE INDEX IF NOT EXISTS idx_vision_goals_project ON vision_goals(project_id);

-- Add comment for documentation
COMMENT ON COLUMN vision_goals.project_id IS 'Project scope - each goal belongs to one project';
