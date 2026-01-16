-- Migration 074: Fix enforcement gaps (G4-G7)
-- Closes gaps discovered during testing protocol execution
-- Task: task-93dcd252

-- ============================================================
-- G4: Update enforce_plan_approval_before_running
-- Remove backwards compatibility bypass - require spirit record
-- ============================================================

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

        -- STRICT: Spirit record MUST exist with approved status
        IF spirit_status IS NULL THEN
            RAISE EXCEPTION 'Task % requires spirit record with approved plan. Use "st approve %" to create one.',
                NEW.id, NEW.id;
        ELSIF spirit_status != 'approved' THEN
            RAISE EXCEPTION 'Cannot start task without approved plan. Current plan_status: %. Use "st approve %" to approve.',
                spirit_status, NEW.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger already exists from 068, function replacement is sufficient

-- ============================================================
-- G5: Add session variable bypass for amendment approval
-- Allow approved amendments to modify locked criteria
-- ============================================================

CREATE OR REPLACE FUNCTION prevent_locked_criteria_changes()
RETURNS TRIGGER AS $$
BEGIN
    -- Allow bypass for amendment approval process
    -- The approve_amendment function sets this session variable
    IF current_setting('app.amendment_approval', true) = 'true' THEN
        RETURN NEW;
    END IF;

    -- Block changes to verify_command when criterion is locked
    IF OLD.is_locked = TRUE AND NEW.verify_command IS DISTINCT FROM OLD.verify_command THEN
        RAISE EXCEPTION 'Cannot modify verify_command on locked criterion %. Use st criterion amend to request changes.', OLD.criterion_id;
    END IF;

    -- Also prevent unlocking (only system can unlock via amendment approval)
    IF OLD.is_locked = TRUE AND NEW.is_locked = FALSE THEN
        RAISE EXCEPTION 'Cannot unlock criterion %. Locked criteria can only be modified via amendment protocol.', OLD.criterion_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger already exists from 073, function replacement is sufficient

-- ============================================================
-- G6: Enforce verified=TRUE only when verification_status='passed'
-- Block direct setting of verified without going through verification
-- ============================================================

CREATE OR REPLACE FUNCTION enforce_verified_requires_verification_status()
RETURNS TRIGGER AS $$
BEGIN
    -- Only check when changing verified from FALSE to TRUE
    IF OLD.verified = FALSE AND NEW.verified = TRUE THEN
        -- Must have verification_status = 'passed' or 'skipped' (for human overrides)
        IF NEW.verification_status NOT IN ('passed', 'skipped') THEN
            RAISE EXCEPTION 'Cannot set verified=TRUE without verification_status=passed. Criterion % has status=%. Use system verification.',
                OLD.criterion_id, NEW.verification_status;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_verified_requires_verification_status ON task_acceptance_criteria;

CREATE TRIGGER enforce_verified_requires_verification_status
    BEFORE UPDATE ON task_acceptance_criteria
    FOR EACH ROW
    EXECUTE FUNCTION enforce_verified_requires_verification_status();

-- ============================================================
-- G7: Enforce subtask completion before QA pass
-- Block QA pass if any subtasks are incomplete
-- ============================================================

CREATE OR REPLACE FUNCTION enforce_subtasks_complete_before_qa_pass()
RETURNS TRIGGER AS $$
DECLARE
    incomplete_count INTEGER;
BEGIN
    -- Only check when setting qa_status to 'passed'
    IF NEW.qa_status = 'passed' AND (OLD.qa_status IS NULL OR OLD.qa_status != 'passed') THEN
        -- Count incomplete subtasks
        SELECT COUNT(*) INTO incomplete_count
        FROM task_subtasks
        WHERE task_id = NEW.id AND passes = FALSE;

        IF incomplete_count > 0 THEN
            RAISE EXCEPTION 'Cannot pass QA with % incomplete subtasks. Use "st subtask list %" to see them.',
                incomplete_count, NEW.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_subtasks_complete_before_qa_pass ON tasks;

CREATE TRIGGER enforce_subtasks_complete_before_qa_pass
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION enforce_subtasks_complete_before_qa_pass();

-- ============================================================
-- Summary of changes:
-- G4: Tasks without spirit record now blocked (no backwards compat)
-- G5: Amendment approval can set session var to bypass lock check
-- G6: verified=TRUE requires verification_status='passed'
-- G7: QA pass requires all subtasks to be complete
-- ============================================================
