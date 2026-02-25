-- Migration 007: Create observation_queue table
-- Fire-and-forget queue for tool execution capture before async extraction

CREATE TABLE IF NOT EXISTS observation_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id TEXT NOT NULL REFERENCES projects(id),
    session_id TEXT NOT NULL,
    agent_type TEXT NOT NULL,  -- 'claude-code', 'claude', 'gemini'
    tool_name TEXT NOT NULL,
    tool_input JSONB,
    tool_output TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'processing', 'processed', 'failed'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
);

-- Index for fetching pending items for processing
CREATE INDEX IF NOT EXISTS idx_observation_queue_status_created
ON observation_queue(status, created_at)
WHERE status = 'pending';

-- Index for project-scoped queries
CREATE INDEX IF NOT EXISTS idx_observation_queue_project
ON observation_queue(project_id);

COMMENT ON TABLE observation_queue IS 'Fire-and-forget queue for tool executions awaiting observation extraction';
