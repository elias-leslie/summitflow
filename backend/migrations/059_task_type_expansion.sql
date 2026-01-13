-- Migration 059: Expand task_type to include autonomous execution types
-- Adds: refactor, debt, regression types for autonomous task pickup
-- Valid types: feature, bug, task, refactor, debt, regression

-- No column change needed (VARCHAR(20) already accommodates)
-- Add comment documenting valid values

COMMENT ON COLUMN tasks.task_type IS 'Task type: feature, bug, task, refactor, debt, regression';

-- Update existing tasks based on labels to new types
-- Tasks with "auto-generated" AND "code-health" labels -> debt
-- Tasks with "regression" label -> regression
-- Tasks with "auto-generated" AND NOT "code-health" AND NOT "regression" -> refactor

-- Migrate debt tasks (code-health findings)
UPDATE tasks
SET task_type = 'debt'
WHERE task_type = 'task'
  AND labels @> ARRAY['auto-generated']
  AND labels @> ARRAY['code-health'];

-- Migrate regression tasks
UPDATE tasks
SET task_type = 'regression'
WHERE task_type = 'task'
  AND labels @> ARRAY['regression'];

-- Migrate refactor tasks (auto-generated but not debt or regression)
UPDATE tasks
SET task_type = 'refactor'
WHERE task_type = 'task'
  AND labels @> ARRAY['auto-generated']
  AND NOT labels @> ARRAY['code-health']
  AND NOT labels @> ARRAY['regression'];

-- Verify migration
DO $$
DECLARE
    debt_count INTEGER;
    regression_count INTEGER;
    refactor_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO debt_count FROM tasks WHERE task_type = 'debt';
    SELECT COUNT(*) INTO regression_count FROM tasks WHERE task_type = 'regression';
    SELECT COUNT(*) INTO refactor_count FROM tasks WHERE task_type = 'refactor';

    RAISE NOTICE 'Migration complete: % debt, % regression, % refactor tasks',
        debt_count, regression_count, refactor_count;
END $$;
