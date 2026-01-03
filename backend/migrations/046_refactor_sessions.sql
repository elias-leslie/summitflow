-- Migration: 046_refactor_sessions.sql
-- Description: Create refactor_sessions table for persisting baseline scan IDs
-- Replaces volatile /tmp file storage with database persistence

CREATE TABLE refactor_sessions (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(50) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,  -- SummitFlow task ID (e.g., task-abc123)

    -- Baseline tracking
    baseline_scan_id INTEGER REFERENCES scan_history(id),
    baseline_commit_sha VARCHAR(40),  -- Git commit SHA at baseline

    -- Session metadata
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- 'active', 'completed', 'abandoned'
    session_id TEXT,  -- Claude session ID if applicable

    -- Final comparison
    final_scan_id INTEGER REFERENCES scan_history(id),
    final_commit_sha VARCHAR(40),

    -- Metrics
    subtasks_planned INTEGER DEFAULT 0,
    subtasks_completed INTEGER DEFAULT 0,

    -- Timestamps
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    UNIQUE(project_id, task_id)
);

-- Indexes
CREATE INDEX idx_refactor_sessions_project ON refactor_sessions(project_id);
CREATE INDEX idx_refactor_sessions_status ON refactor_sessions(status) WHERE status = 'active';
CREATE INDEX idx_refactor_sessions_task ON refactor_sessions(task_id);

COMMENT ON TABLE refactor_sessions IS 'Persists refactor_it baseline scan IDs and session metadata, replacing volatile /tmp storage';
COMMENT ON COLUMN refactor_sessions.baseline_scan_id IS 'Reference to scan_history entry for the baseline scan';
COMMENT ON COLUMN refactor_sessions.baseline_commit_sha IS 'Git commit SHA when baseline was taken';
