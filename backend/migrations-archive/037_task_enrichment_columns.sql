-- Migration: 037_task_enrichment_columns.sql
-- Purpose: Add enrichment workflow columns to tasks table
-- Created: 2025-12-31

-- Add enrichment columns to tasks table
-- These support the AI-powered task enrichment workflow

-- raw_request stores the original user input before AI enrichment
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS raw_request TEXT;

-- enrichment_status tracks the state of AI enrichment workflow
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS enrichment_status TEXT DEFAULT 'none';

-- enriched_by tracks which AI model performed the enrichment
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS enriched_by TEXT;

-- enriched_at tracks when enrichment completed
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMP WITH TIME ZONE;

-- Add CHECK constraint for valid enrichment statuses
-- Only add if it doesn't exist (avoid duplicate constraint error)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'tasks_enrichment_status_check'
    ) THEN
        ALTER TABLE tasks ADD CONSTRAINT tasks_enrichment_status_check
        CHECK (enrichment_status IN ('none', 'draft', 'enriching', 'review', 'discussing', 'accepted', 'failed'));
    END IF;
END $$;

-- Index for filtering by enrichment status
CREATE INDEX IF NOT EXISTS idx_tasks_enrichment_status ON tasks(enrichment_status);

-- Comments for documentation
COMMENT ON COLUMN tasks.raw_request IS 'Original user input before AI enrichment';
COMMENT ON COLUMN tasks.enrichment_status IS 'Workflow state: none, draft, enriching, review, discussing, accepted, failed';
COMMENT ON COLUMN tasks.enriched_by IS 'AI model that performed enrichment (e.g., claude-opus-4.5)';
COMMENT ON COLUMN tasks.enriched_at IS 'Timestamp when enrichment completed';
