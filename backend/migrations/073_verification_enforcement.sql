-- Migration 073: Verification Enforcement
-- Adds columns to task_acceptance_criteria for TDD-style verification enforcement

-- Step 1: Preflight validation columns
ALTER TABLE task_acceptance_criteria
ADD COLUMN IF NOT EXISTS preflight_status VARCHAR(20) DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS preflight_output TEXT,
ADD COLUMN IF NOT EXISTS preflight_at TIMESTAMPTZ;

-- Step 2: Criteria locking columns
ALTER TABLE task_acceptance_criteria
ADD COLUMN IF NOT EXISTS is_locked BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ;

-- Step 3: Verification status columns (distinct from preflight)
ALTER TABLE task_acceptance_criteria
ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS verification_output TEXT,
ADD COLUMN IF NOT EXISTS verification_at TIMESTAMPTZ;

-- Step 4: Attempt tracking for escalation
ALTER TABLE task_acceptance_criteria
ADD COLUMN IF NOT EXISTS verification_attempts INTEGER DEFAULT 0;

-- Step 5: Escalation level (3-2-1: Worker 3, Supervisor 2, Human 1)
ALTER TABLE task_acceptance_criteria
ADD COLUMN IF NOT EXISTS escalation_level VARCHAR(20) DEFAULT 'WORKER';

-- Add CHECK constraint for escalation_level
ALTER TABLE task_acceptance_criteria
DROP CONSTRAINT IF EXISTS task_acceptance_criteria_escalation_level_check;

ALTER TABLE task_acceptance_criteria
ADD CONSTRAINT task_acceptance_criteria_escalation_level_check
CHECK (escalation_level IN ('WORKER', 'SUPERVISOR', 'HUMAN'));

-- Add CHECK constraint for preflight_status
ALTER TABLE task_acceptance_criteria
DROP CONSTRAINT IF EXISTS task_acceptance_criteria_preflight_status_check;

ALTER TABLE task_acceptance_criteria
ADD CONSTRAINT task_acceptance_criteria_preflight_status_check
CHECK (preflight_status IN ('pending', 'valid_fail', 'invalid_pass', 'invalid_crash'));

-- Add CHECK constraint for verification_status
ALTER TABLE task_acceptance_criteria
DROP CONSTRAINT IF EXISTS task_acceptance_criteria_verification_status_check;

ALTER TABLE task_acceptance_criteria
ADD CONSTRAINT task_acceptance_criteria_verification_status_check
CHECK (verification_status IN ('pending', 'passed', 'failed', 'skipped'));

-- ============================================================
-- Part 2: Criterion Amendments Table (for audit trail)
-- ============================================================

CREATE TABLE IF NOT EXISTS criterion_amendments (
    id SERIAL PRIMARY KEY,
    amendment_id VARCHAR(20) NOT NULL UNIQUE,  -- amend-XXXX format
    criterion_id VARCHAR(20) NOT NULL,         -- References criterion being amended
    task_id VARCHAR(50) NOT NULL,              -- Task context

    -- Amendment content
    old_verify_command TEXT,
    new_verify_command TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence TEXT,                              -- Path to screenshot/log artifact

    -- Status tracking
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'auto_approved')),

    -- Approval metadata
    approved_by VARCHAR(50),                    -- 'supervisor', 'human', or user ID
    approval_reason TEXT,

    -- Preflight validation of new command
    preflight_status VARCHAR(20),
    preflight_output TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,

    -- Foreign key to task_acceptance_criteria
    CONSTRAINT fk_criterion_amendments_criterion
        FOREIGN KEY (task_id, criterion_id)
        REFERENCES task_acceptance_criteria(task_id, criterion_id)
        ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_criterion_amendments_criterion_id
ON criterion_amendments(criterion_id);

CREATE INDEX IF NOT EXISTS idx_criterion_amendments_task_id
ON criterion_amendments(task_id);

CREATE INDEX IF NOT EXISTS idx_criterion_amendments_status
ON criterion_amendments(status);

-- ============================================================
-- Part 3: Trigger to auto-lock criteria when task starts running
-- ============================================================

-- Function to lock all criteria when task status changes to 'running'
CREATE OR REPLACE FUNCTION lock_criteria_on_task_running()
RETURNS TRIGGER AS $$
BEGIN
    -- Only act when status changes TO 'running'
    IF NEW.status = 'running' AND (OLD.status IS NULL OR OLD.status != 'running') THEN
        UPDATE task_acceptance_criteria
        SET is_locked = TRUE,
            locked_at = NOW(),
            updated_at = NOW()
        WHERE task_id = NEW.id
          AND is_locked = FALSE;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop existing trigger if any
DROP TRIGGER IF EXISTS lock_criteria_on_running ON tasks;

-- Create trigger on tasks table
CREATE TRIGGER lock_criteria_on_running
    AFTER UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION lock_criteria_on_task_running();

-- ============================================================
-- Part 4: Trigger to prevent verify_command changes when locked
-- ============================================================

-- Function to block verify_command updates on locked criteria
CREATE OR REPLACE FUNCTION prevent_locked_criteria_changes()
RETURNS TRIGGER AS $$
BEGIN
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

-- Drop existing trigger if any
DROP TRIGGER IF EXISTS prevent_locked_criteria_changes ON task_acceptance_criteria;

-- Create trigger on task_acceptance_criteria
CREATE TRIGGER prevent_locked_criteria_changes
    BEFORE UPDATE ON task_acceptance_criteria
    FOR EACH ROW
    EXECUTE FUNCTION prevent_locked_criteria_changes();

-- ============================================================
-- Part 5: Drop conflicting step completion trigger
-- The old trigger enforced "all steps must pass before subtask pass"
-- This is replaced by verification-based gating (criteria pass = subtask pass)
-- Per decision d5: demote step gate to logging only
-- ============================================================

DROP TRIGGER IF EXISTS enforce_steps_complete_before_subtask_pass ON task_subtasks;
DROP FUNCTION IF EXISTS enforce_steps_complete();

-- ============================================================
-- Part 6: Add human_reviewing and ai_reviewing to tasks status
-- ============================================================

-- Add CHECK constraint for tasks.status including new verification statuses
-- First drop any existing constraint
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;

-- Add new constraint with all valid statuses including human_reviewing and ai_reviewing
ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
CHECK (status IN (
    'pending', 'ready', 'running', 'paused', 'blocked',
    'needs_review', 'completed', 'cancelled', 'failed',
    'human_reviewing', 'ai_reviewing'
));

-- ============================================================
-- Part 7: Trigger to compute task status from criteria escalation
-- ============================================================

-- Function to update task status based on criteria escalation levels
CREATE OR REPLACE FUNCTION update_task_status_from_criteria()
RETURNS TRIGGER AS $$
DECLARE
    v_task_id TEXT;
    v_human_count INT;
    v_supervisor_count INT;
    v_all_passed BOOLEAN;
    v_current_status TEXT;
BEGIN
    -- Get task_id from the affected criterion
    v_task_id := COALESCE(NEW.task_id, OLD.task_id);

    -- Get current task status
    SELECT status INTO v_current_status FROM tasks WHERE id = v_task_id;

    -- Only update if task is in an active state
    IF v_current_status NOT IN ('running', 'human_reviewing', 'ai_reviewing') THEN
        RETURN NEW;
    END IF;

    -- Count criteria at each escalation level
    SELECT
        COALESCE(SUM(CASE WHEN escalation_level = 'HUMAN' THEN 1 ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN escalation_level = 'SUPERVISOR' THEN 1 ELSE 0 END), 0),
        COALESCE(bool_and(verification_status IN ('passed', 'skipped')), FALSE)
    INTO v_human_count, v_supervisor_count, v_all_passed
    FROM task_acceptance_criteria
    WHERE task_id = v_task_id;

    -- Update task status based on criteria state
    -- Note: Don't change to 'completed' - that requires QA flow
    IF v_human_count > 0 THEN
        UPDATE tasks SET status = 'human_reviewing' WHERE id = v_task_id AND status != 'human_reviewing';
    ELSIF v_supervisor_count > 0 THEN
        UPDATE tasks SET status = 'ai_reviewing' WHERE id = v_task_id AND status != 'ai_reviewing';
    ELSIF v_all_passed THEN
        -- All criteria passed - move to needs_review for QA flow
        UPDATE tasks SET status = 'needs_review' WHERE id = v_task_id AND status NOT IN ('needs_review', 'completed');
    ELSE
        -- Keep as running
        UPDATE tasks SET status = 'running' WHERE id = v_task_id AND status NOT IN ('running', 'needs_review', 'completed');
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop existing trigger if any
DROP TRIGGER IF EXISTS update_task_status_from_criteria ON task_acceptance_criteria;

-- Create trigger that fires on escalation_level or verification_status changes
CREATE TRIGGER update_task_status_from_criteria
    AFTER UPDATE OF escalation_level, verification_status ON task_acceptance_criteria
    FOR EACH ROW
    EXECUTE FUNCTION update_task_status_from_criteria();
