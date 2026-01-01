-- Migration: Drop dead columns from tasks table
-- Date: 2026-01-01
-- Description: Remove spec_content and current_criterion_id columns
--              These columns are no longer used after TDD architecture refactor.
--              - spec_content: replaced by plan_content and task_subtasks
--              - current_criterion_id: replaced by capability_criteria junction

-- =============================================================================
-- DROP DEAD COLUMNS
-- =============================================================================

-- spec_content was never used in the new architecture
ALTER TABLE tasks DROP COLUMN IF EXISTS spec_content;

-- current_criterion_id is obsolete (criteria are now in junction tables)
ALTER TABLE tasks DROP COLUMN IF EXISTS current_criterion_id;

-- =============================================================================
-- VERIFY
-- =============================================================================

-- This will fail if columns still exist
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tasks'
        AND column_name IN ('spec_content', 'current_criterion_id')
    ) THEN
        RAISE EXCEPTION 'Columns were not dropped successfully!';
    END IF;
END $$;
