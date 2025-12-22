-- Migration 009: Create session_diary table
-- Session summaries for pattern learning

CREATE TABLE IF NOT EXISTS session_diary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id TEXT NOT NULL REFERENCES projects(id),
    session_id TEXT NOT NULL,
    task_id TEXT REFERENCES tasks(id),  -- Optional: linked task
    agent_type TEXT NOT NULL,

    -- Session metrics
    duration_seconds INTEGER,
    tokens_used INTEGER,
    discovery_tokens INTEGER,  -- Tokens spent on observation extraction

    -- Outcome tracking
    outcome TEXT NOT NULL,  -- 'success', 'partial', 'failed'
    observation_type TEXT,  -- Primary type from observations in session
    concepts TEXT[] DEFAULT '{}',  -- Aggregated concepts from session

    -- What happened
    what_worked JSONB,  -- List of successful approaches
    what_failed JSONB,  -- List of failed attempts
    user_corrections JSONB,  -- User feedback/corrections during session
    patterns_used JSONB,  -- Patterns that were applied

    -- Reflection (filled during reflection phase)
    reflected_at TIMESTAMPTZ,
    reflection_notes TEXT,
    patterns_generated JSONB,  -- Pattern IDs generated from this diary entry

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Standard indexes
CREATE INDEX IF NOT EXISTS idx_session_diary_project ON session_diary(project_id);
CREATE INDEX IF NOT EXISTS idx_session_diary_created ON session_diary(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_diary_outcome ON session_diary(project_id, outcome);
CREATE INDEX IF NOT EXISTS idx_session_diary_unreflected ON session_diary(project_id, reflected_at)
WHERE reflected_at IS NULL;

COMMENT ON TABLE session_diary IS 'Session summaries for pattern learning and reflection';
