-- Migration 008: Create observations table
-- Extracted observations from tool executions with full-text search

CREATE TABLE IF NOT EXISTS observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id TEXT NOT NULL REFERENCES projects(id),
    session_id TEXT NOT NULL,
    agent_type TEXT NOT NULL,  -- 'claude-code', 'claude', 'gemini'

    -- Observation taxonomy
    observation_type TEXT NOT NULL,  -- 'pattern', 'decision', 'error', 'constraint', 'architecture', 'user_preference'
    concepts TEXT[] NOT NULL DEFAULT '{}',  -- 'debugging', 'code_patterns', 'dependencies', 'security', 'performance', 'testing', 'configuration'

    -- Structured content
    title TEXT NOT NULL,
    subtitle TEXT,
    narrative TEXT,  -- LLM-generated narrative for human reading
    facts JSONB,  -- Structured key-value pairs for programmatic use

    -- Source tracking
    files_read TEXT[] DEFAULT '{}',
    files_modified TEXT[] DEFAULT '{}',
    tool_name TEXT,
    tool_input JSONB,

    -- Token tracking
    discovery_tokens INTEGER DEFAULT 0,  -- Tokens used for extraction

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Full-text search vector (auto-generated)
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(subtitle, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(narrative, '')), 'C')
    ) STORED
);

-- GIN index for full-text search
CREATE INDEX IF NOT EXISTS idx_observations_search ON observations USING GIN(search_vector);

-- Standard query indexes
CREATE INDEX IF NOT EXISTS idx_observations_project ON observations(project_id);
CREATE INDEX IF NOT EXISTS idx_observations_session ON observations(session_id);
CREATE INDEX IF NOT EXISTS idx_observations_type ON observations(project_id, observation_type);
CREATE INDEX IF NOT EXISTS idx_observations_agent ON observations(project_id, agent_type);
CREATE INDEX IF NOT EXISTS idx_observations_created ON observations(project_id, created_at DESC);

-- Array index for files_modified queries
CREATE INDEX IF NOT EXISTS idx_observations_files ON observations USING GIN(files_modified);

COMMENT ON TABLE observations IS 'Extracted observations from tool executions with semantic search';
