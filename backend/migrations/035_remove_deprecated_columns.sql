-- Migration: Remove deprecated columns/tables after TDD architecture migration
-- Date: 2025-12-31
-- Description: Clean up old JSONB and junction tables replaced by unified criteria schema

-- =============================================================================
-- PRE-CHECKS
-- =============================================================================

-- Verify migration was completed (criterion_tests should exist and have data)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM criterion_tests LIMIT 1
    ) THEN
        RAISE EXCEPTION 'criterion_tests is empty. Run migrate_tdd_architecture.py first!';
    END IF;
END $$;

-- =============================================================================
-- DROP DEPRECATED COLUMNS FROM tasks TABLE
-- =============================================================================

-- Remove acceptance_criteria JSONB column (data migrated to task_criteria junction)
-- Note: All tasks had null/empty values, so no data loss
ALTER TABLE tasks DROP COLUMN IF EXISTS acceptance_criteria;

-- =============================================================================
-- DROP DEPRECATED capability_tests TABLE
-- =============================================================================

-- Remove old capability_tests table (replaced by criterion_tests)
-- Data was migrated: each capability_tests row became:
--   1. acceptance_criteria row with criterion "Test passes: {test_name}"
--   2. capability_criteria junction linking criterion to capability
--   3. criterion_tests junction linking test to criterion
DROP TABLE IF EXISTS capability_tests;

-- =============================================================================
-- CLEANUP INDEXES (if they still exist)
-- =============================================================================

-- These indexes were on the dropped table, but ensure cleanup
DROP INDEX IF EXISTS idx_capability_tests_capability;
DROP INDEX IF EXISTS idx_capability_tests_test;

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON COLUMN tasks.objective IS 'Task objective (TDD: what the task should accomplish)';
COMMENT ON COLUMN tasks.current_phase IS 'Current phase of task execution';
COMMENT ON COLUMN tasks.verification_result IS 'Result of last verification run';
