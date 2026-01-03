-- Add verification_url column to capabilities table
-- DEPRECATED: This feature was never used (0 capabilities with verification_url set as of 2026-01-03).
-- Column to be dropped in Phase 4. See tdd-spec-review design doc.

ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS verification_url TEXT;

COMMENT ON COLUMN capabilities.verification_url IS 'DEPRECATED: To be dropped. Optional URL to capture evidence from when capability tests pass';
