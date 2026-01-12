-- Add automation_settings JSONB column to projects table
-- For crowdsourced idea automation configuration

ALTER TABLE projects ADD COLUMN IF NOT EXISTS automation_settings JSONB DEFAULT '{
    "schedule_preset": "nightly",
    "cron_expression": "0 3 * * *",
    "daily_budget_usd": 5.0,
    "primary_agent": "gemini",
    "secondary_agent": "claude",
    "enabled": false
}'::jsonb;

COMMENT ON COLUMN projects.automation_settings IS 'Crowdsourced idea automation configuration: schedule, budget, agents, enabled';
