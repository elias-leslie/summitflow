-- Migration 052: Evidence Capture Jobs and Regressions
-- Tracks scheduled capture jobs and detected regressions
-- Part of Evidence Capture System (task-74a098a5)

-- Evidence capture jobs - track batch capture operations
CREATE TABLE IF NOT EXISTS evidence_capture_jobs (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_type VARCHAR(50) NOT NULL,
    scope VARCHAR(50) NOT NULL DEFAULT 'project',
    target_entry_ids INTEGER[],
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    entries_captured INTEGER DEFAULT 0,
    regressions_found INTEGER DEFAULT 0,
    triggered_by VARCHAR(100),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_capture_jobs_project ON evidence_capture_jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_capture_jobs_status ON evidence_capture_jobs(status);
CREATE INDEX IF NOT EXISTS idx_capture_jobs_created ON evidence_capture_jobs(created_at DESC);

-- Evidence regressions - detected differences from baseline
CREATE TABLE IF NOT EXISTS evidence_regressions (
    id SERIAL PRIMARY KEY,
    evidence_id INTEGER NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    baseline_evidence_id INTEGER REFERENCES evidence(id) ON DELETE SET NULL,
    regression_type VARCHAR(50) NOT NULL,
    pixel_diff_pct FLOAT,
    console_errors_added INTEGER DEFAULT 0,
    ai_analysis JSONB,
    severity VARCHAR(20) DEFAULT 'unknown',
    status VARCHAR(50) NOT NULL DEFAULT 'detected',
    linked_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    reviewed_by VARCHAR(100),
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_regressions_evidence ON evidence_regressions(evidence_id);
CREATE INDEX IF NOT EXISTS idx_regressions_status ON evidence_regressions(status);
CREATE INDEX IF NOT EXISTS idx_regressions_task ON evidence_regressions(linked_task_id);
CREATE INDEX IF NOT EXISTS idx_regressions_created ON evidence_regressions(created_at DESC);
