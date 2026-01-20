-- Migration 084: Create mockups table for design artifacts
-- Stores mockups with full provenance metadata for AI-generated designs

CREATE TABLE IF NOT EXISTS mockups (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    mockup_id VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    mockup_type VARCHAR(50) NOT NULL DEFAULT 'component',
    file_path TEXT,
    content TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'generated',
    approved_at TIMESTAMPTZ,
    approved_by VARCHAR(100),
    applied_at TIMESTAMPTZ,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    page_path TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    parent_mockup_id INTEGER REFERENCES mockups(id) ON DELETE SET NULL,
    generator VARCHAR(50),
    generation_prompt TEXT,
    generation_time_ms INTEGER,
    iteration_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT mockups_project_mockup_unique UNIQUE(project_id, mockup_id),
    CONSTRAINT mockups_type_check CHECK (mockup_type IN ('component', 'page', 'layout', 'icon', 'illustration')),
    CONSTRAINT mockups_status_check CHECK (status IN ('generated', 'pending_approval', 'approved', 'rejected', 'applied', 'archived'))
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_mockups_project ON mockups(project_id);
CREATE INDEX IF NOT EXISTS idx_mockups_task ON mockups(task_id);
CREATE INDEX IF NOT EXISTS idx_mockups_status ON mockups(status);
CREATE INDEX IF NOT EXISTS idx_mockups_page_path ON mockups(page_path);
CREATE INDEX IF NOT EXISTS idx_mockups_parent ON mockups(parent_mockup_id);
CREATE INDEX IF NOT EXISTS idx_mockups_generator ON mockups(generator);
CREATE INDEX IF NOT EXISTS idx_mockups_created ON mockups(created_at DESC);

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_mockups_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_mockups_updated_at ON mockups;
CREATE TRIGGER trigger_mockups_updated_at
    BEFORE UPDATE ON mockups
    FOR EACH ROW
    EXECUTE FUNCTION update_mockups_updated_at();
