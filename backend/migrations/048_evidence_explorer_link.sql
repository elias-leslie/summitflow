-- Migration 048: Evidence-Explorer Link
-- Links evidence table to explorer_entries for explorer-driven evidence capture
-- Part of Evidence Capture System (task-74a098a5)

-- Add explorer_entry_id as the new primary link for evidence
-- Capability linkage remains for backwards compatibility but is now optional
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS explorer_entry_id INTEGER REFERENCES explorer_entries(id) ON DELETE SET NULL;

-- Update evidence_type to support new universal types
-- Default remains 'screenshot' for backwards compatibility, but now supports more types
ALTER TABLE evidence
    ALTER COLUMN evidence_type TYPE VARCHAR(50);

-- Add environment column to distinguish local/staging/production captures
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS environment VARCHAR(50) DEFAULT 'local';

-- Add sub_element_selector for capturing specific elements within a page
-- (e.g., tabs, accordions, expanded rows)
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS sub_element_selector VARCHAR(500);

-- Add viewport_name for multi-viewport captures (desktop/tablet/mobile)
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS viewport_name VARCHAR(50);

-- Create index for explorer entry lookups
CREATE INDEX IF NOT EXISTS idx_evidence_explorer_entry ON evidence(explorer_entry_id);

-- Create index for environment filtering
CREATE INDEX IF NOT EXISTS idx_evidence_environment ON evidence(environment);

-- Create index for viewport filtering
CREATE INDEX IF NOT EXISTS idx_evidence_viewport ON evidence(viewport_name) WHERE viewport_name IS NOT NULL;

-- Backfill explorer_entry_id on existing evidence records by matching URLs
-- Evidence file_path typically contains the URL that was captured
-- Match against explorer_entries.path (which is the URL path)
UPDATE evidence e
SET explorer_entry_id = ee.id
FROM explorer_entries ee
WHERE e.explorer_entry_id IS NULL
  AND e.project_id = ee.project_id
  AND ee.entry_type = 'page'
  AND e.file_path LIKE '%' || ee.path || '%';
