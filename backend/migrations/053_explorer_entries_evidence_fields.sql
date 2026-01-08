-- Migration 053: Add denormalized evidence fields to explorer_entries
-- Enables quick evidence coverage visibility without JOINs
-- Part of Evidence Capture System (task-74a098a5)

ALTER TABLE explorer_entries
    ADD COLUMN IF NOT EXISTS evidence_count INTEGER DEFAULT 0;

ALTER TABLE explorer_entries
    ADD COLUMN IF NOT EXISTS last_evidence_at TIMESTAMPTZ;

-- Create index for evidence status queries
CREATE INDEX IF NOT EXISTS idx_explorer_entries_evidence ON explorer_entries(evidence_count)
    WHERE evidence_count > 0;
