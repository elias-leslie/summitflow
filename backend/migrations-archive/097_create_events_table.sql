-- Migration: 097_create_events_table.sql
-- Purpose: Create unified events table for execution tracing
-- Created: 2026-01-25
-- Rationale: Replace fragmented progress_log TEXT, in-memory buffers, and ephemeral Redis pub/sub
--            with a single source of truth for all execution events (OTel-inspired schema)

-- Create events table with OTel-inspired schema
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    trace_id TEXT NOT NULL,
    span_id TEXT,
    parent_span_id TEXT,
    event_type TEXT NOT NULL,
    name TEXT,
    source TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    visibility TEXT NOT NULL DEFAULT 'user',
    message TEXT,
    attributes JSONB DEFAULT '{}',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Primary query path: fetch events by trace_id (execution run)
CREATE INDEX IF NOT EXISTS idx_events_trace_id ON events(trace_id);

-- Composite index for project-scoped time-ordered queries
CREATE INDEX IF NOT EXISTS idx_events_project_timestamp ON events(project_id, timestamp DESC);

-- Visibility filter (user vs internal events)
CREATE INDEX IF NOT EXISTS idx_events_visibility ON events(visibility);

-- Level filter (error, warning, info, debug)
CREATE INDEX IF NOT EXISTS idx_events_level ON events(level);

-- Span hierarchy navigation
CREATE INDEX IF NOT EXISTS idx_events_parent_span ON events(parent_span_id) WHERE parent_span_id IS NOT NULL;

-- Add check constraints for enum-like columns
ALTER TABLE events ADD CONSTRAINT events_level_check CHECK (
    level = ANY (ARRAY['error', 'warning', 'info', 'debug'])
);

ALTER TABLE events ADD CONSTRAINT events_visibility_check CHECK (
    visibility = ANY (ARRAY['user', 'internal', 'debug'])
);

COMMENT ON TABLE events IS 'Unified execution events with OTel-inspired tracing';
COMMENT ON COLUMN events.trace_id IS 'Execution trace ID (typically task_id)';
COMMENT ON COLUMN events.span_id IS 'Unique span identifier within trace';
COMMENT ON COLUMN events.parent_span_id IS 'Parent span for hierarchical tracing';
COMMENT ON COLUMN events.event_type IS 'Event type (state_change, progress, error, log, etc)';
COMMENT ON COLUMN events.source IS 'Event source (orchestrator, worker, agent, system)';
COMMENT ON COLUMN events.level IS 'Log level: error, warning, info, debug';
COMMENT ON COLUMN events.visibility IS 'Visibility scope: user (shown in UI), internal, debug';
COMMENT ON COLUMN events.attributes IS 'Structured event metadata as JSONB';
