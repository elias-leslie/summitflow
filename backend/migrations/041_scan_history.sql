-- Migration: 041_scan_history.sql
-- Description: Create scan_history table for tracking all explorer scans
-- with trigger metadata and metrics

-- Create scan_history table
CREATE TABLE scan_history (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(50) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scan_type VARCHAR(50) NOT NULL,  -- 'file', 'page', 'endpoint', 'database', 'task', 'full'

    -- Trigger metadata
    triggered_by VARCHAR(50) NOT NULL DEFAULT 'manual',  -- 'manual', 'refactor_it', 'daily_qa_scan', 'audit_it', 'celery_beat'
    triggered_by_session TEXT,  -- Claude session ID if applicable
    triggered_by_user TEXT,  -- User identifier if applicable
    trigger_context JSONB DEFAULT '{}',  -- Additional context (phase, goal, etc.)

    -- Timing
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,  -- Computed on completion

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'running',  -- 'running', 'completed', 'failed', 'cancelled'
    error_message TEXT,

    -- Metrics
    metrics JSONB DEFAULT '{}',  -- Type-specific metrics (files_scanned, errors_found, etc.)
    entries_found INTEGER DEFAULT 0,
    entries_saved INTEGER DEFAULT 0,

    -- Comparison data
    previous_scan_id INTEGER REFERENCES scan_history(id),
    metrics_delta JSONB DEFAULT '{}',  -- Computed difference from previous scan

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_scan_history_project_type ON scan_history(project_id, scan_type);
CREATE INDEX idx_scan_history_triggered_by ON scan_history(triggered_by);
CREATE INDEX idx_scan_history_started_at ON scan_history(started_at DESC);
CREATE INDEX idx_scan_history_status ON scan_history(status) WHERE status = 'running';

-- Unique constraint to prevent duplicate scans at same timestamp
CREATE UNIQUE INDEX idx_scan_history_unique ON scan_history(project_id, started_at);

-- Comment on table
COMMENT ON TABLE scan_history IS 'Tracks all explorer scan executions with trigger metadata and metrics for trend visualization';
COMMENT ON COLUMN scan_history.triggered_by IS 'Source that initiated the scan: manual, refactor_it, daily_qa_scan, audit_it, celery_beat';
COMMENT ON COLUMN scan_history.trigger_context IS 'Additional context about the trigger (phase name, goal, baseline_scan_id, etc.)';
COMMENT ON COLUMN scan_history.metrics_delta IS 'Computed difference from previous_scan_id metrics (added, removed, changed counts)';
