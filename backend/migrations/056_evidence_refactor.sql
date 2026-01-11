-- Migration 056: Evidence System Refactor
-- Removes capability dependencies, adds mockup support, adds CHECK constraint
-- Part of Evidence System Overhaul (task-51044751)

-- Step 1: Remove deprecated capability-related columns
-- The evidence system now uses task_id and/or explorer_entry_id instead

-- Drop the capability_id index first
DROP INDEX IF EXISTS idx_evidence_capability;

-- Drop the deprecated criterion_id (string-based, replaced by criterion_db_id)
DROP INDEX IF EXISTS idx_evidence_criterion;

-- Remove deprecated columns
ALTER TABLE evidence DROP COLUMN IF EXISTS capability_id;
ALTER TABLE evidence DROP COLUMN IF EXISTS criterion_id;

-- Step 2: Add CHECK constraint to enforce task_id OR explorer_entry_id
-- This ensures every evidence record is linked to either a task or an explorer entry
ALTER TABLE evidence ADD CONSTRAINT evidence_task_or_entry_check
    CHECK (task_id IS NOT NULL OR explorer_entry_id IS NOT NULL);

-- Step 3: Add mockup support columns
-- linked_evidence_id: Links mockup to the original screenshot it's compared against
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS linked_evidence_id INTEGER REFERENCES evidence(id) ON DELETE SET NULL;

-- mockup_status: Tracks the mockup approval workflow
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS mockup_status VARCHAR(20)
    CHECK (mockup_status IN ('generated', 'pending_approval', 'approved', 'rejected') OR mockup_status IS NULL);

-- Create index for linked evidence lookups
CREATE INDEX IF NOT EXISTS idx_evidence_linked ON evidence(linked_evidence_id) WHERE linked_evidence_id IS NOT NULL;

-- Step 4: Define valid evidence types via CHECK constraint
-- Keeping as VARCHAR for flexibility but constraining allowed values
ALTER TABLE evidence ADD CONSTRAINT evidence_type_check
    CHECK (evidence_type IN ('screenshot', 'mockup', 'test-output', 'api-response', 'console_error', 'evidence'));

-- Note: 'evidence' is kept for backwards compatibility with existing records
