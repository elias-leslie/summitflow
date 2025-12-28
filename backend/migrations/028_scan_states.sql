-- Migration: Add scan_states table
-- Description: Persists scan state across backend restarts
-- Date: 2025-12-27

CREATE TABLE IF NOT EXISTS scan_states (
    project_id VARCHAR(255) PRIMARY KEY,
    status VARCHAR(50) NOT NULL DEFAULT 'idle',
    current_type VARCHAR(50),
    types_total INTEGER DEFAULT 0,
    types_completed INTEGER DEFAULT 0,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error TEXT,
    results JSONB DEFAULT '{}',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scan_states_status ON scan_states(status);

COMMENT ON TABLE scan_states IS 'Persists scan state across backend restarts';
COMMENT ON COLUMN scan_states.status IS 'Scan status: idle, running, completed, failed';
COMMENT ON COLUMN scan_states.current_type IS 'Currently scanning type (file, page, endpoint, etc.)';
COMMENT ON COLUMN scan_states.results IS 'JSON object with counts per scanned type';
