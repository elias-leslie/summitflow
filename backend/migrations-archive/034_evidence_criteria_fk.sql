-- Migration: 034_evidence_criteria_fk.sql
-- Purpose: Add FK columns to evidence table for criterion and test_run linkage
-- Created: 2025-12-31

-- Add metadata column if it doesn't exist (for storing legacy expires_at)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'evidence' AND column_name = 'metadata'
    ) THEN
        ALTER TABLE evidence ADD COLUMN metadata JSONB DEFAULT '{}';
    END IF;
END $$;

-- Preserve expires_at values in metadata before dropping column (must run after metadata column exists)
UPDATE evidence
SET metadata = jsonb_set(
    COALESCE(metadata, '{}'),
    '{legacy_expires_at}',
    to_jsonb(expires_at)
)
WHERE expires_at IS NOT NULL;

-- Add criterion_db_id column with FK to acceptance_criteria
-- Uses ON DELETE CASCADE so evidence is deleted when criterion is deleted
ALTER TABLE evidence
ADD COLUMN IF NOT EXISTS criterion_db_id INTEGER REFERENCES acceptance_criteria(id) ON DELETE CASCADE;

-- Add test_run_id column with FK to test_runs
-- Uses ON DELETE CASCADE so evidence is deleted when test_run is deleted
ALTER TABLE evidence
ADD COLUMN IF NOT EXISTS test_run_id INTEGER REFERENCES test_runs(id) ON DELETE CASCADE;

-- Add auto_captured flag to track evidence that was auto-captured on test pass
ALTER TABLE evidence
ADD COLUMN IF NOT EXISTS auto_captured BOOLEAN DEFAULT FALSE;

-- Drop expires_at column (expiration logic being removed)
ALTER TABLE evidence DROP COLUMN IF EXISTS expires_at;

-- Create indexes for the new FK columns
CREATE INDEX IF NOT EXISTS idx_evidence_criterion_db ON evidence(criterion_db_id);
CREATE INDEX IF NOT EXISTS idx_evidence_test_run ON evidence(test_run_id);

-- Add comments explaining the new columns
COMMENT ON COLUMN evidence.criterion_db_id IS 'FK to acceptance_criteria.id - links evidence to specific criterion';
COMMENT ON COLUMN evidence.test_run_id IS 'FK to test_runs.id - links evidence to test run that captured it';
COMMENT ON COLUMN evidence.auto_captured IS 'True if evidence was auto-captured on test pass';
