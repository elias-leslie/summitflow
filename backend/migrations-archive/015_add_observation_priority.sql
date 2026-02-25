-- Migration 015: Add priority column to observations
-- Priority levels for retrieval ranking: high, medium, low

ALTER TABLE observations ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'medium';

-- Index for priority-based queries
CREATE INDEX IF NOT EXISTS idx_observations_priority ON observations(project_id, priority);

COMMENT ON COLUMN observations.priority IS 'Observation priority: high (errors, decisions, user prefs), medium (patterns, architecture), low (constraints)';
