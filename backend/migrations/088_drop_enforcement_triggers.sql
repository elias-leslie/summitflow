-- Migration 088: Drop enforcement triggers and simplify schema
-- Purpose: Remove complex database-enforced verification in favor of application-level enforcement
-- Task: task-bf5cf769 (Task System Friction & Bypass Fixes)
-- Created: 2026-01-21

-- ============================================================
-- Step 1: Drop 7 enforcement triggers
-- These are being replaced by application-level enforcement in st close
-- ============================================================

-- From migration 073
DROP TRIGGER IF EXISTS lock_criteria_on_running ON tasks;
DROP FUNCTION IF EXISTS lock_criteria_on_task_running();

DROP TRIGGER IF EXISTS prevent_locked_criteria_changes ON task_acceptance_criteria;
DROP FUNCTION IF EXISTS prevent_locked_criteria_changes();

DROP TRIGGER IF EXISTS update_task_status_from_criteria ON task_acceptance_criteria;
DROP FUNCTION IF EXISTS update_task_status_from_criteria();

-- From migration 074
DROP TRIGGER IF EXISTS enforce_verified_requires_verification_status ON task_acceptance_criteria;
DROP FUNCTION IF EXISTS enforce_verified_requires_verification_status();

-- From migration 068
DROP TRIGGER IF EXISTS enforce_criteria_verified_before_qa_pass ON tasks;
DROP FUNCTION IF EXISTS enforce_criteria_verified_before_qa_pass();

DROP TRIGGER IF EXISTS enforce_qa_signoff_before_complete ON tasks;
DROP FUNCTION IF EXISTS enforce_qa_signoff_before_complete();

DROP TRIGGER IF EXISTS enforce_plan_approval_before_running ON tasks;
DROP FUNCTION IF EXISTS enforce_plan_approval_before_running();

-- Also drop these triggers that were created in 068 (not in the task list but related)
DROP TRIGGER IF EXISTS enforce_criteria_exist_for_complex ON tasks;
DROP FUNCTION IF EXISTS enforce_criteria_exist_for_complex();

-- ============================================================
-- Step 2: Drop dead columns from task_acceptance_criteria
-- These columns were part of the verification enforcement system
-- ============================================================

ALTER TABLE task_acceptance_criteria
    DROP COLUMN IF EXISTS is_locked,
    DROP COLUMN IF EXISTS locked_at,
    DROP COLUMN IF EXISTS preflight_status,
    DROP COLUMN IF EXISTS preflight_output,
    DROP COLUMN IF EXISTS preflight_at,
    DROP COLUMN IF EXISTS verification_status,
    DROP COLUMN IF EXISTS verification_output,
    DROP COLUMN IF EXISTS verification_at,
    DROP COLUMN IF EXISTS verification_attempts,
    DROP COLUMN IF EXISTS escalation_level;

-- Drop the constraints that referenced these columns
ALTER TABLE task_acceptance_criteria
    DROP CONSTRAINT IF EXISTS task_acceptance_criteria_escalation_level_check,
    DROP CONSTRAINT IF EXISTS task_acceptance_criteria_preflight_status_check,
    DROP CONSTRAINT IF EXISTS task_acceptance_criteria_verification_status_check;

-- ============================================================
-- Step 3: Drop criterion_amendments table
-- The amendment protocol is no longer needed without locked criteria
-- ============================================================

DROP TABLE IF EXISTS criterion_amendments;

-- ============================================================
-- Step 4: Drop legacy criteria tables
-- These were replaced by task_acceptance_criteria in migration 064
-- ============================================================

-- Must drop in order due to foreign key dependencies
DROP TABLE IF EXISTS criterion_tests;       -- Depends on acceptance_criteria and tests (tests already dropped)
DROP TABLE IF EXISTS task_criteria;         -- Depends on acceptance_criteria
DROP TABLE IF EXISTS capability_criteria;   -- Depends on acceptance_criteria
DROP TABLE IF EXISTS acceptance_criteria;   -- Main legacy table

-- ============================================================
-- Summary:
-- - 7 enforcement triggers dropped (lock, prevent_changes, verification_status, update_status, qa_pass, qa_complete, plan_approval)
-- - 1 additional trigger dropped (criteria_exist_for_complex)
-- - 10 dead columns dropped from task_acceptance_criteria
-- - 1 table dropped (criterion_amendments)
-- - 4 legacy tables dropped (criterion_tests, task_criteria, capability_criteria, acceptance_criteria)
-- ============================================================
