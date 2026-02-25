-- Migration 050: Project Evidence Configuration
-- Per-project settings for evidence capture (schedules, viewports, thresholds)
-- Part of Evidence Capture System (task-74a098a5)

CREATE TABLE IF NOT EXISTS project_evidence_config (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    enabled_types TEXT[] DEFAULT ARRAY['screenshot', 'console_log'],
    capture_schedule VARCHAR(50) DEFAULT 'daily',
    environments TEXT[] DEFAULT ARRAY['local'],
    viewports JSONB DEFAULT '[
        {"name": "desktop", "width": 1280, "height": 720},
        {"name": "tablet", "width": 768, "height": 1024},
        {"name": "mobile", "width": 390, "height": 844}
    ]'::jsonb,
    auto_expand_elements BOOLEAN DEFAULT true,
    regression_threshold FLOAT DEFAULT 0.05,
    ai_review_enabled BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create update trigger for updated_at
CREATE OR REPLACE FUNCTION update_project_evidence_config_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_project_evidence_config_updated ON project_evidence_config;
CREATE TRIGGER trg_project_evidence_config_updated
    BEFORE UPDATE ON project_evidence_config
    FOR EACH ROW
    EXECUTE FUNCTION update_project_evidence_config_updated_at();
