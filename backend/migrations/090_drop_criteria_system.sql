-- Migration: 090_drop_criteria_system.sql
-- Purpose: Remove task-level acceptance criteria in favor of step-level verification
-- Created: 2026-01-21
-- Rationale: Coding agents work best with tight feedback loops at the step level.
--            Task-level criteria add complexity without improving agent effectiveness.
--            The "code → verify → fix if fail → repeat" loop works best per-step.

-- ============================================================
-- Step 1: Drop criterion_subtask_map (junction table)
-- Must drop first due to foreign key to task_acceptance_criteria
-- ============================================================

DROP TABLE IF EXISTS criterion_subtask_map;

-- ============================================================
-- Step 2: Drop task_acceptance_criteria
-- Verification now happens at step level via verify_command
-- ============================================================

DROP TABLE IF EXISTS task_acceptance_criteria;

-- ============================================================
-- Summary:
-- - criterion_subtask_map dropped (was linking criteria to subtasks)
-- - task_acceptance_criteria dropped (replaced by step-level verify_command)
-- - Step-level verification added in migration 089
-- ============================================================
