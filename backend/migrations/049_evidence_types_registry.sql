-- Migration 049: Evidence Types Registry
-- Central registry of evidence types with capture methods and entry type applicability
-- Part of Evidence Capture System (task-74a098a5)

CREATE TABLE IF NOT EXISTS evidence_types (
    id SERIAL PRIMARY KEY,
    type_id VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    capture_method VARCHAR(50) NOT NULL,
    applicable_entry_types TEXT[] NOT NULL DEFAULT '{}',
    schema JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed data for core evidence types
INSERT INTO evidence_types (type_id, name, description, capture_method, applicable_entry_types, schema) VALUES
    ('screenshot', 'Screenshot', 'Browser screenshot capture', 'browser', ARRAY['page'], '{"format": "png", "full_page": true}'::jsonb),
    ('console_log', 'Console Log', 'Browser console output capture', 'browser', ARRAY['page'], '{"include_network": true}'::jsonb),
    ('api_response', 'API Response', 'HTTP API response capture', 'http', ARRAY['endpoint'], '{"max_body_size": 102400}'::jsonb),
    ('test_result', 'Test Result', 'Test execution result', 'test_runner', ARRAY['file'], '{"include_output": true}'::jsonb),
    ('schema_snapshot', 'Schema Snapshot', 'Database schema state', 'sql', ARRAY['table'], '{"include_row_count": true}'::jsonb),
    ('task_execution', 'Task Execution', 'Celery task execution trace', 'celery', ARRAY['task'], '{"include_traceback": true}'::jsonb),
    ('performance', 'Performance Metrics', 'Page performance metrics', 'browser', ARRAY['page'], '{"metrics": ["LCP", "FID", "CLS"]}'::jsonb),
    ('accessibility', 'Accessibility Report', 'Accessibility audit results', 'browser', ARRAY['page'], '{"standard": "WCAG21"}'::jsonb)
ON CONFLICT (type_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_evidence_types_capture_method ON evidence_types(capture_method);
