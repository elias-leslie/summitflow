-- Migration: 042_qa_issues.sql
-- Description: Create qa_issues table for tracking QA-detected issues
-- that can be linked to SummitFlow tasks for self-healing

-- Create qa_issues table
CREATE TABLE qa_issues (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(50) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Issue identification
    issue_type VARCHAR(50) NOT NULL,  -- 'complexity', 'stale_file', 'missing_test', 'dead_code', etc.
    severity VARCHAR(20) NOT NULL DEFAULT 'medium',  -- 'low', 'medium', 'high', 'critical'
    file_path TEXT,  -- File that has the issue (nullable for non-file issues)
    entry_id INTEGER REFERENCES explorer_entries(id) ON DELETE SET NULL,

    -- Issue details
    title VARCHAR(255) NOT NULL,
    description TEXT,
    metadata JSONB DEFAULT '{}',  -- Type-specific data (complexity score, lines, etc.)

    -- Detection tracking
    first_detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    detected_in_scan_id INTEGER REFERENCES scan_history(id),
    detection_count INTEGER DEFAULT 1,

    -- Resolution tracking
    status VARCHAR(20) NOT NULL DEFAULT 'open',  -- 'open', 'resolved', 'wontfix', 'duplicate'
    resolved_at TIMESTAMPTZ,
    resolution_scan_id INTEGER REFERENCES scan_history(id),
    resolution_reason TEXT,

    -- SummitFlow task link (self-healing)
    st_task_id TEXT,  -- Links to SummitFlow tasks table

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_qa_issues_project_status ON qa_issues(project_id, status);
CREATE INDEX idx_qa_issues_project_type ON qa_issues(project_id, issue_type);
CREATE INDEX idx_qa_issues_file ON qa_issues(file_path) WHERE file_path IS NOT NULL;
CREATE INDEX idx_qa_issues_entry ON qa_issues(entry_id) WHERE entry_id IS NOT NULL;

-- Partial index for task links (self-healing)
CREATE INDEX idx_qa_issues_task_link ON qa_issues(st_task_id) WHERE st_task_id IS NOT NULL;

-- Unique constraint to prevent duplicate issues for same file/type
CREATE UNIQUE INDEX idx_qa_issues_unique ON qa_issues(project_id, issue_type, file_path)
    WHERE file_path IS NOT NULL AND status = 'open';

-- Comments
COMMENT ON TABLE qa_issues IS 'Tracks QA-detected issues for self-healing task automation';
COMMENT ON COLUMN qa_issues.st_task_id IS 'Links to SummitFlow task for auto-close on resolution';
COMMENT ON COLUMN qa_issues.detection_count IS 'Number of times this issue was detected (helps identify persistent problems)';
