-- Migration: Rename feature_id to capability_id in evidence table
-- Part of features → capabilities migration

-- Rename the column
ALTER TABLE evidence
RENAME COLUMN feature_id TO capability_id;

-- Increase VARCHAR size to accommodate longer capability IDs
ALTER TABLE evidence
ALTER COLUMN capability_id TYPE VARCHAR(50);

-- Drop old index and create new one
DROP INDEX IF EXISTS idx_evidence_feature;
CREATE INDEX IF NOT EXISTS idx_evidence_capability ON evidence(capability_id);
