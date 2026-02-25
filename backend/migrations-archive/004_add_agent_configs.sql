-- Migration 004: Add agent_configs column to projects table
-- For storing per-project agent configuration (Claude/Gemini)

-- Add agent_configs JSONB column to projects table
ALTER TABLE projects
ADD COLUMN IF NOT EXISTS agent_configs JSONB DEFAULT '{
    "claude_enabled": true,
    "gemini_enabled": true,
    "default_agent": "gemini",
    "claude_model": "sonnet",
    "gemini_model": "gemini-2.5-flash"
}'::jsonb;

-- Add comment for documentation
COMMENT ON COLUMN projects.agent_configs IS 'Agent configuration for this project. Structure:
{
    "claude_enabled": boolean,      -- Whether Claude is enabled
    "gemini_enabled": boolean,      -- Whether Gemini is enabled
    "default_agent": string,        -- Default agent ("claude" or "gemini")
    "claude_model": string,         -- Claude model (sonnet, opus, haiku)
    "gemini_model": string          -- Gemini model (gemini-2.5-pro, gemini-2.5-flash)
}';
