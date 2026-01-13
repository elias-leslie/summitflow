-- Migration 060: Document autonomous schedule settings in agent_configs JSONB
-- New fields in agent_configs:
--   autonomous_start_hour: int (0-23) - Hour when execution can start
--   autonomous_end_hour: int (1-24) - Hour when execution must stop (24 = midnight)
--   autonomous_max_concurrent: int (1-3) - Max concurrent tasks per project

-- No schema change needed (JSONB accommodates new keys dynamically)
-- This migration serves as documentation and sets defaults for existing projects

-- Update projects that have autonomous_enabled=true but missing new fields
UPDATE projects
SET agent_configs = agent_configs || jsonb_build_object(
    'autonomous_start_hour', 0,
    'autonomous_end_hour', 24,
    'autonomous_max_concurrent', 1
)
WHERE agent_configs ? 'autonomous_enabled'
  AND (agent_configs->>'autonomous_enabled')::boolean = true
  AND NOT (agent_configs ? 'autonomous_start_hour');

-- Verify migration
DO $$
DECLARE
    updated_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO updated_count
    FROM projects
    WHERE agent_configs ? 'autonomous_start_hour';

    RAISE NOTICE 'Migration complete: % projects have autonomous schedule settings', updated_count;
END $$;
