-- Migration: 069_data_migration_spirit.sql
-- Purpose: Migrate task spirit data from tasks table to task_spirit table
-- Created: 2026-01-16
-- Task: task-48ae552b (Normalize task schema)
--
-- Expected counts before migration:
--   tasks: 494
--   with objective: 128
--   with spirit_anti: 36
--   with decisions: 33
--   with constraints: 31
--   with done_when: 37
--   completed: 147
--   with labels: 412

-- =============================================================================
-- Step 1: Copy spirit data from tasks to task_spirit
-- =============================================================================

-- Insert into task_spirit for all tasks that have at least one spirit field populated
-- Use ON CONFLICT to handle re-runs safely
INSERT INTO task_spirit (task_id, objective, spirit_anti, decisions, constraints, done_when, context, complexity)
SELECT
    id,
    COALESCE(objective, ''),  -- objective is NOT NULL, default to empty string
    spirit_anti,
    COALESCE(decisions, '[]'::jsonb),
    COALESCE(constraints, '[]'::jsonb),
    COALESCE(done_when, '[]'::jsonb),
    '{}'::jsonb,  -- Initialize context as empty JSONB
    complexity    -- Copy complexity from tasks table
FROM tasks
WHERE objective IS NOT NULL
   OR spirit_anti IS NOT NULL
   OR decisions IS NOT NULL
   OR constraints IS NOT NULL
   OR done_when IS NOT NULL
ON CONFLICT (task_id) DO UPDATE SET
    objective = EXCLUDED.objective,
    spirit_anti = EXCLUDED.spirit_anti,
    decisions = EXCLUDED.decisions,
    constraints = EXCLUDED.constraints,
    done_when = EXCLUDED.done_when,
    complexity = EXCLUDED.complexity,
    updated_at = NOW();

-- =============================================================================
-- Step 2: Set plan_status='approved' for all existing tasks (grandfather clause)
-- =============================================================================

-- All existing tasks should be considered "approved" so they can still run
UPDATE task_spirit
SET plan_status = 'approved',
    plan_approved_at = NOW(),
    plan_approved_by = 'migration-069-grandfather'
WHERE plan_status = 'draft';

-- =============================================================================
-- Step 3: Set qa_status='skipped' for completed tasks (grandfather clause)
-- =============================================================================

-- All completed tasks should bypass QA requirement
UPDATE tasks
SET qa_status = 'skipped',
    qa_signoff_at = NOW(),
    qa_signoff_by = 'migration-069-grandfather'
WHERE status = 'completed' AND qa_status = 'pending';
