-- Migration 020: Add memory configuration defaults to existing projects
-- Purpose: Ensure all projects have memory_enabled flags in agent_configs

-- Update existing projects to include memory defaults in agent_configs
-- JSONB || operator merges objects, with right side taking precedence
-- We use COALESCE to handle NULL agent_configs
UPDATE projects
SET agent_configs = COALESCE(agent_configs, '{}'::jsonb) || jsonb_build_object(
    'memory_enabled', COALESCE((agent_configs->>'memory_enabled')::boolean, true),
    'observations_enabled', COALESCE((agent_configs->>'observations_enabled')::boolean, true),
    'diary_enabled', COALESCE((agent_configs->>'diary_enabled')::boolean, true),
    'patterns_enabled', COALESCE((agent_configs->>'patterns_enabled')::boolean, true),
    'checkpoints_enabled', COALESCE((agent_configs->>'checkpoints_enabled')::boolean, true),
    'context_injection_enabled', COALESCE((agent_configs->>'context_injection_enabled')::boolean, true)
)
WHERE agent_configs IS NULL
   OR agent_configs->>'memory_enabled' IS NULL;
