-- Migration: 068_qa_signoff_workflow.sql
-- Purpose: Add QA signoff columns and workflow enforcement triggers
-- Created: 2026-01-16
-- Task: task-48ae552b (Normalize task schema)

-- =============================================================================
-- Step 1: Add QA signoff columns to tasks table
-- =============================================================================

-- QA gate columns for task completion workflow
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS qa_status VARCHAR(20) DEFAULT 'pending' CHECK (qa_status IN ('pending', 'passed', 'failed', 'skipped'));
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS qa_signoff_at TIMESTAMPTZ;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS qa_signoff_by TEXT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS qa_issues JSONB DEFAULT '[]';

COMMENT ON COLUMN tasks.qa_status IS 'QA gate: pending|passed|failed|skipped. SIMPLE can skip, STANDARD/COMPLEX must pass.';
COMMENT ON COLUMN tasks.qa_issues IS 'JSONB array of {issue, severity, resolved} discovered during QA';

-- =============================================================================
-- Step 2: Trigger - enforce_plan_approval_before_running
-- =============================================================================

CREATE OR REPLACE FUNCTION enforce_plan_approval_before_running()
RETURNS TRIGGER AS $$
DECLARE
    spirit_status VARCHAR(20);
BEGIN
    -- Only check when transitioning TO 'running' status
    IF NEW.status = 'running' AND (OLD.status IS NULL OR OLD.status != 'running') THEN
        -- Check task_spirit table for plan approval
        SELECT plan_status INTO spirit_status
        FROM task_spirit
        WHERE task_id = NEW.id;

        -- Allow if no spirit record exists (backwards compatibility) or if approved
        IF spirit_status IS NOT NULL AND spirit_status != 'approved' THEN
            RAISE EXCEPTION 'Cannot start task without approved plan. Current plan_status: %. Use "st approve %" to approve.',
                spirit_status, NEW.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_plan_approval_before_running ON tasks;
CREATE TRIGGER enforce_plan_approval_before_running
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION enforce_plan_approval_before_running();

-- =============================================================================
-- Step 3: Trigger - enforce_qa_signoff_before_complete
-- =============================================================================

CREATE OR REPLACE FUNCTION enforce_qa_signoff_before_complete()
RETURNS TRIGGER AS $$
BEGIN
    -- Only check when transitioning TO 'completed' status
    IF NEW.status = 'completed' AND (OLD.status IS NULL OR OLD.status != 'completed') THEN
        -- QA must be passed or skipped
        IF NEW.qa_status NOT IN ('passed', 'skipped') THEN
            RAISE EXCEPTION 'Cannot complete task without QA signoff. Current qa_status: %. Use "st qa pass|skip %" first.',
                NEW.qa_status, NEW.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_qa_signoff_before_complete ON tasks;
CREATE TRIGGER enforce_qa_signoff_before_complete
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION enforce_qa_signoff_before_complete();

-- =============================================================================
-- Step 4: Trigger - enforce_criteria_verified_before_qa_pass
-- =============================================================================

CREATE OR REPLACE FUNCTION enforce_criteria_verified_before_qa_pass()
RETURNS TRIGGER AS $$
DECLARE
    unverified_count INTEGER;
BEGIN
    -- Only check when setting qa_status to 'passed'
    IF NEW.qa_status = 'passed' AND (OLD.qa_status IS NULL OR OLD.qa_status != 'passed') THEN
        -- Count unverified criteria
        SELECT COUNT(*) INTO unverified_count
        FROM task_acceptance_criteria
        WHERE task_id = NEW.id AND verified = FALSE;

        IF unverified_count > 0 THEN
            RAISE EXCEPTION 'Cannot pass QA with % unverified criteria. Use "st criterion list --task %" to see them.',
                unverified_count, NEW.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_criteria_verified_before_qa_pass ON tasks;
CREATE TRIGGER enforce_criteria_verified_before_qa_pass
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION enforce_criteria_verified_before_qa_pass();

-- =============================================================================
-- Step 5: Trigger - enforce_criteria_exist_for_complex (STANDARD/COMPLEX)
-- =============================================================================

-- Add complexity column to task_spirit if not exists
ALTER TABLE task_spirit ADD COLUMN IF NOT EXISTS complexity VARCHAR(20) CHECK (complexity IN ('SIMPLE', 'STANDARD', 'COMPLEX'));

CREATE OR REPLACE FUNCTION enforce_criteria_exist_for_complex()
RETURNS TRIGGER AS $$
DECLARE
    task_complexity VARCHAR(20);
    criteria_count INTEGER;
BEGIN
    -- Only check when transitioning TO 'running' status
    IF NEW.status = 'running' AND (OLD.status IS NULL OR OLD.status != 'running') THEN
        -- Get complexity from task_spirit
        SELECT complexity INTO task_complexity
        FROM task_spirit
        WHERE task_id = NEW.id;

        -- Only enforce for STANDARD and COMPLEX tasks
        IF task_complexity IN ('STANDARD', 'COMPLEX') THEN
            SELECT COUNT(*) INTO criteria_count
            FROM task_acceptance_criteria
            WHERE task_id = NEW.id;

            IF criteria_count = 0 THEN
                RAISE EXCEPTION '% tasks require at least one acceptance criterion. Use "st criterion create --task %" to add criteria.',
                    task_complexity, NEW.id;
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_criteria_exist_for_complex ON tasks;
CREATE TRIGGER enforce_criteria_exist_for_complex
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION enforce_criteria_exist_for_complex();

-- =============================================================================
-- Step 6: Trigger - enforce_subtask_dependencies
-- =============================================================================

-- Note: task_subtasks doesn't have a 'status' column - it uses passes boolean
-- We'll check dependencies when updating passes to TRUE
CREATE OR REPLACE FUNCTION enforce_subtask_dependencies()
RETURNS TRIGGER AS $$
DECLARE
    incomplete_deps TEXT[];
BEGIN
    -- Only check when setting passes to TRUE (marking subtask complete)
    IF NEW.passes = TRUE AND (OLD.passes IS NULL OR OLD.passes = FALSE) THEN
        -- Check for incomplete dependencies
        SELECT ARRAY_AGG(dep.subtask_id)
        INTO incomplete_deps
        FROM subtask_dependencies sd
        JOIN task_subtasks dep ON sd.depends_on_subtask_id = dep.id
        WHERE sd.subtask_id = NEW.id AND dep.passes = FALSE;

        IF incomplete_deps IS NOT NULL AND array_length(incomplete_deps, 1) > 0 THEN
            RAISE EXCEPTION 'Cannot pass subtask % with incomplete dependencies: %',
                NEW.subtask_id, array_to_string(incomplete_deps, ', ');
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_subtask_dependencies ON task_subtasks;
CREATE TRIGGER enforce_subtask_dependencies
    BEFORE UPDATE ON task_subtasks
    FOR EACH ROW
    EXECUTE FUNCTION enforce_subtask_dependencies();

-- =============================================================================
-- Step 7: Trigger - enforce_steps_complete_before_subtask_pass
-- =============================================================================

CREATE OR REPLACE FUNCTION enforce_steps_complete_before_subtask_pass()
RETURNS TRIGGER AS $$
DECLARE
    incomplete_steps INTEGER;
BEGIN
    -- Only check when setting passes to TRUE
    IF NEW.passes = TRUE AND (OLD.passes IS NULL OR OLD.passes = FALSE) THEN
        -- Count incomplete steps
        SELECT COUNT(*) INTO incomplete_steps
        FROM task_subtask_steps
        WHERE subtask_id = NEW.id AND passes = FALSE;

        IF incomplete_steps > 0 THEN
            RAISE EXCEPTION 'Cannot pass subtask % with % incomplete steps. Use "st step list" to see them.',
                NEW.subtask_id, incomplete_steps;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_steps_complete_before_subtask_pass ON task_subtasks;
CREATE TRIGGER enforce_steps_complete_before_subtask_pass
    BEFORE UPDATE ON task_subtasks
    FOR EACH ROW
    EXECUTE FUNCTION enforce_steps_complete_before_subtask_pass();

-- =============================================================================
-- Create indexes for efficient trigger queries
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_tasks_qa_status ON tasks(qa_status);
CREATE INDEX IF NOT EXISTS idx_task_spirit_complexity ON task_spirit(complexity);
