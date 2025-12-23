-- Migration 018: Add entities column to observations
-- Purpose: Store extracted entities for improved retrieval
-- Entity types: project, file, error_type, tool, concept

ALTER TABLE observations ADD COLUMN IF NOT EXISTS entities JSONB DEFAULT '[]';

-- GIN index for efficient JSONB queries
CREATE INDEX IF NOT EXISTS idx_observations_entities ON observations USING GIN(entities);

COMMENT ON COLUMN observations.entities IS 'Extracted entities: [{type: "file", value: "auth.py"}, {type: "error_type", value: "ImportError"}]';
