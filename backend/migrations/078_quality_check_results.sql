-- Migration 078: Create quality_check_results table
-- Tracks results from dt quality gate checks (pytest, ruff, mypy, eslint/biome, tsc)
-- Per decision d2: Use typed columns instead of JSONB metadata blob

CREATE TABLE IF NOT EXISTS quality_check_results (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Check identification
    check_type VARCHAR(20) NOT NULL CHECK (check_type IN ('pytest', 'ruff', 'mypy', 'biome', 'tsc')),
    check_name VARCHAR(100),  -- e.g., specific test name or rule violated

    -- Result data
    status VARCHAR(20) NOT NULL CHECK (status IN ('pass', 'fail', 'error', 'skipped')),
    error_count INTEGER DEFAULT 0,
    warning_count INTEGER DEFAULT 0,

    -- Error details (structured, not JSONB blob)
    error_message TEXT,
    file_path TEXT,
    line_number INTEGER,
    column_number INTEGER,

    -- Execution context
    run_duration_ms INTEGER,
    git_sha VARCHAR(40),
    triggered_by VARCHAR(50),  -- 'commit', 'manual', 'ci', 'agent'

    -- Fix tracking
    fix_attempted BOOLEAN DEFAULT FALSE,
    fix_attempts INTEGER DEFAULT 0,
    fixed_at TIMESTAMPTZ,
    fixed_by TEXT,  -- agent or user that fixed it

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_quality_check_project ON quality_check_results(project_id);
CREATE INDEX IF NOT EXISTS idx_quality_check_type ON quality_check_results(check_type);
CREATE INDEX IF NOT EXISTS idx_quality_check_status ON quality_check_results(status);
CREATE INDEX IF NOT EXISTS idx_quality_check_created ON quality_check_results(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_check_unfixed ON quality_check_results(project_id, status)
    WHERE status = 'fail' AND fixed_at IS NULL;

-- Composite index for project+type queries
CREATE INDEX IF NOT EXISTS idx_quality_check_project_type ON quality_check_results(project_id, check_type);

COMMENT ON TABLE quality_check_results IS 'Stores results from dt quality gate checks. Tracks failures, fix attempts, and resolution status.';
COMMENT ON COLUMN quality_check_results.check_type IS 'Type of quality check: pytest, ruff, mypy, biome, tsc';
COMMENT ON COLUMN quality_check_results.triggered_by IS 'What triggered this check: commit, manual, ci, agent';
