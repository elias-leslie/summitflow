-- Migration: 093_fix_step_not_subtask.sql
-- Purpose: Change plan_defect fix reference from subtask to step within same subtask
-- Created: 2026-01-22
-- Rationale: Fix steps are simpler and more localized than fix subtasks.
--            A plan defect in step 1.1.1 should be fixed by adding step 1.1.3,
--            not by creating an entirely new subtask.

-- =============================================================================
-- Step 1: Add fix_step_number column
-- =============================================================================

ALTER TABLE task_subtask_steps
ADD COLUMN IF NOT EXISTS fix_step_number INTEGER;

COMMENT ON COLUMN task_subtask_steps.fix_step_number IS
'For plan_defect status: the step number within the same subtask that provides correct verification';

-- =============================================================================
-- Step 2: Migrate existing data (convert subtask references to NULL for now)
-- =============================================================================

-- Existing fix_subtask_id references are incompatible with new design
-- Clear them - affected tasks will need manual re-verification
UPDATE task_subtask_steps
SET fix_step_number = NULL
WHERE status = 'plan_defect' AND fix_subtask_id IS NOT NULL;

-- =============================================================================
-- Step 3: Drop old column
-- =============================================================================

ALTER TABLE task_subtask_steps DROP COLUMN IF EXISTS fix_subtask_id;
