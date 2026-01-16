-- Migration 072: Drop deprecated columns from tasks table
-- CAUTION: Run after verifying all data has been migrated to normalized tables
--
-- Pre-migration checklist:
-- 1. Verify task_spirit has all objective/spirit_anti/decisions/constraints/done_when data
-- 2. Verify task_labels has all labels data
-- 3. Verify no application code reads from these columns directly (use task_spirit instead)
-- 4. Take a full database backup before running
--
-- Columns being dropped (moved to task_spirit):
-- - objective
-- - spirit_anti
-- - decisions
-- - constraints
-- - done_when
--
-- Columns being dropped (moved to task_labels):
-- - labels
--
-- Columns being dropped (legacy/unused):
-- - plan_content (deprecated, use task_subtasks/task_subtask_steps)

-- Step 1: Verify data migration is complete
DO $$
DECLARE
    unmigrated_count INTEGER;
BEGIN
    -- Check for tasks with data but no task_spirit record
    SELECT count(*) INTO unmigrated_count
    FROM tasks t
    LEFT JOIN task_spirit ts ON t.id = ts.task_id
    WHERE ts.task_id IS NULL
      AND (t.objective IS NOT NULL
           OR t.spirit_anti IS NOT NULL
           OR t.decisions IS NOT NULL
           OR t.constraints IS NOT NULL
           OR t.done_when IS NOT NULL);

    IF unmigrated_count > 0 THEN
        RAISE EXCEPTION 'Cannot proceed: % tasks have data in deprecated columns but no task_spirit record', unmigrated_count;
    END IF;
END $$;

-- Step 2: Drop columns moved to task_spirit
ALTER TABLE tasks DROP COLUMN IF EXISTS objective;
ALTER TABLE tasks DROP COLUMN IF EXISTS spirit_anti;
ALTER TABLE tasks DROP COLUMN IF EXISTS decisions;
ALTER TABLE tasks DROP COLUMN IF EXISTS constraints;
ALTER TABLE tasks DROP COLUMN IF EXISTS done_when;

-- Step 3: Drop labels column (moved to task_labels)
ALTER TABLE tasks DROP COLUMN IF EXISTS labels;

-- Step 4: Drop legacy plan_content column
ALTER TABLE tasks DROP COLUMN IF EXISTS plan_content;

-- Step 5: Drop other deprecated columns (if present)
-- These were used for legacy features no longer needed
ALTER TABLE tasks DROP COLUMN IF EXISTS acceptance_criteria;

-- Verify final column count
DO $$
DECLARE
    col_count INTEGER;
BEGIN
    SELECT count(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'tasks' AND table_schema = 'public';

    RAISE NOTICE 'Final tasks table column count: %', col_count;

    -- Target is ~37 columns (45 - 8 dropped)
    IF col_count > 40 THEN
        RAISE WARNING 'Column count (%) is higher than expected. Review remaining columns.', col_count;
    END IF;
END $$;
