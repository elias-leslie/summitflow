-- Migration: 043_context_access_log.sql
-- Description: Create context_access_log table for tracking memory pattern expansions
-- Part of Memory Effectiveness Measurement (task-e975adf2)

-- Create context_access_log table
CREATE TABLE context_access_log (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(50) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Session tracking
    session_id TEXT NOT NULL,  -- Claude Code session ID

    -- Entity being expanded
    entity_type VARCHAR(50) NOT NULL,  -- 'pattern', 'observation', 'diary'
    entity_id TEXT NOT NULL,  -- ID of the pattern/observation/diary entry

    -- When the expansion happened
    expanded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Task correlation (for outcome tracking)
    task_id TEXT,  -- SummitFlow task being worked on (if any)
    task_outcome VARCHAR(20),  -- 'success', 'partial', 'failure' (backfilled from session diary)

    -- Access source tracking (for CLI vs injection analysis)
    access_source VARCHAR(20) NOT NULL DEFAULT 'api',  -- 'injection' (session-start), 'cli' (member-dis), 'api' (manual)

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_context_access_session ON context_access_log(session_id);
CREATE INDEX idx_context_access_entity ON context_access_log(entity_type, entity_id);
CREATE INDEX idx_context_access_expanded ON context_access_log(expanded_at);
CREATE INDEX idx_context_access_source ON context_access_log(access_source);

-- Composite index for pattern effectiveness analysis
CREATE INDEX idx_context_access_pattern_outcome
ON context_access_log(entity_type, entity_id, task_outcome)
WHERE entity_type = 'pattern' AND task_outcome IS NOT NULL;

-- Index for task correlation queries
CREATE INDEX idx_context_access_task ON context_access_log(task_id)
WHERE task_id IS NOT NULL;

-- Comments
COMMENT ON TABLE context_access_log IS 'Tracks when memory entities (patterns, observations) are expanded/accessed by agents';
COMMENT ON COLUMN context_access_log.entity_type IS 'Type of memory entity: pattern, observation, diary';
COMMENT ON COLUMN context_access_log.task_outcome IS 'Outcome of the task session (success/partial/failure) - backfilled from session_diary';
COMMENT ON COLUMN context_access_log.access_source IS 'How the access happened: injection (session-start), cli (member-dis), api (manual endpoint)';
