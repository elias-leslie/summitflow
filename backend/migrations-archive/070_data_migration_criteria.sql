-- Migration: 070_data_migration_criteria.sql
-- Purpose: Migrate acceptance criteria from shared to task-scoped
-- Created: 2026-01-16
-- Task: task-48ae552b (Normalize task schema)
--
-- Source: acceptance_criteria (934 rows) + task_criteria (416 links)

-- =============================================================================
-- Step 4: Copy acceptance_criteria + task_criteria -> task_acceptance_criteria
-- =============================================================================

-- Join task_criteria with acceptance_criteria to create task-scoped criteria
-- This denormalizes the shared criteria into task-specific rows
INSERT INTO task_acceptance_criteria (
    task_id, criterion_id, criterion, category,
    verify_type, verify_by, verify_command, expected_output,
    verified, verified_at, verified_by_actual, display_order
)
SELECT
    tc.task_id,
    ac.criterion_id,
    ac.criterion,
    ac.category,
    -- Infer verify_type from verify_command content
    CASE
        WHEN ac.verify_command IS NULL THEN 'manual'
        WHEN ac.verify_command LIKE '%ba %' OR ac.verify_command LIKE '%browser%' THEN 'browser'
        WHEN ac.verify_command LIKE '%curl%' OR ac.verify_command LIKE '%http%' THEN 'api'
        ELSE 'command'
    END as verify_type,
    COALESCE(ac.verify_by, 'test'),
    ac.verify_command,
    ac.expected_output,
    tc.verified,
    tc.verified_at,
    tc.verified_by,
    ROW_NUMBER() OVER (PARTITION BY tc.task_id ORDER BY ac.id) as display_order
FROM task_criteria tc
JOIN acceptance_criteria ac ON tc.criterion_id = ac.id
ON CONFLICT (task_id, criterion_id) DO UPDATE SET
    criterion = EXCLUDED.criterion,
    category = EXCLUDED.category,
    verify_type = EXCLUDED.verify_type,
    verify_by = EXCLUDED.verify_by,
    verify_command = EXCLUDED.verify_command,
    expected_output = EXCLUDED.expected_output,
    verified = EXCLUDED.verified,
    verified_at = EXCLUDED.verified_at,
    verified_by_actual = EXCLUDED.verified_by_actual,
    updated_at = NOW();
