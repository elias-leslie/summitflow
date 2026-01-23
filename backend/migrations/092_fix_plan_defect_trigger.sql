-- Migration: 092_fix_plan_defect_trigger.sql
-- Purpose: Fix enforce_steps_complete_before_subtask_pass trigger to allow plan_defect steps
-- Created: 2026-01-22
-- Issue: Trigger blocks subtask completion when steps have status='plan_defect', but
--        the Python code (subtasks.py) correctly allows plan_defect steps to be skipped.
--        This creates a mismatch where the Python validation passes but DB trigger fails.

-- =============================================================================
-- Fix: Update trigger to exclude plan_defect steps from incomplete count
-- =============================================================================

CREATE OR REPLACE FUNCTION enforce_steps_complete_before_subtask_pass()
RETURNS TRIGGER AS $$
DECLARE
    incomplete_steps INTEGER;
BEGIN
    -- Only check when setting passes to TRUE
    IF NEW.passes = TRUE AND (OLD.passes IS NULL OR OLD.passes = FALSE) THEN
        -- Count incomplete steps, EXCLUDING plan_defect status
        -- plan_defect steps have been acknowledged as plan issues and can be skipped
        SELECT COUNT(*) INTO incomplete_steps
        FROM task_subtask_steps
        WHERE subtask_id = NEW.id
          AND passes = FALSE
          AND (status IS NULL OR status != 'plan_defect');

        IF incomplete_steps > 0 THEN
            RAISE EXCEPTION 'Cannot pass subtask % with % incomplete steps. Use "st step list" to see them.',
                NEW.subtask_id, incomplete_steps;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add comment explaining the plan_defect exception
COMMENT ON FUNCTION enforce_steps_complete_before_subtask_pass() IS
'Enforces that all steps must be complete (passes=true) before a subtask can be marked as passed.
Exception: Steps with status=''plan_defect'' are allowed to be skipped since they represent
acknowledged issues with the plan (wrong verify_command, impossible expected_output, etc.)
rather than implementation failures.';
