-- Migration 011: Create agent_checkpoints table
-- Checkpoint/resume support for agent sessions

CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id TEXT NOT NULL REFERENCES projects(id),
    session_id TEXT NOT NULL,
    agent_type TEXT NOT NULL,

    -- Current state
    current_action TEXT,  -- What the agent was doing
    question TEXT,  -- Question being asked (if any)
    options JSONB,  -- Available choices
    recommendation TEXT,  -- Suggested option

    -- Progress tracking
    completed_steps JSONB,  -- List of completed step descriptions
    remaining_steps JSONB,  -- List of remaining step descriptions
    files_modified JSONB,  -- Files changed during session
    decisions_made JSONB,  -- Key decisions and rationale

    -- Context snapshot
    conversation_summary TEXT,  -- LLM-generated summary of conversation
    context_snapshot JSONB,  -- Additional context data

    -- Metrics
    tokens_used INTEGER,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Query indexes
CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_project
ON agent_checkpoints(project_id);

CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_session
ON agent_checkpoints(session_id);

-- For getting latest checkpoint
CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_session_latest
ON agent_checkpoints(session_id, created_at DESC);

COMMENT ON TABLE agent_checkpoints IS 'Checkpoint/resume support for seamless session handoff';
