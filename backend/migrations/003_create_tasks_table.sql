-- Migration: Create tasks table for agent execution tracking
-- Created: 2025-12-18
-- Purpose: Store task execution state for multi-agent platform

-- ============================================================
-- tasks: Agent execution state for features
-- ============================================================
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,                -- task-001, task-002, etc.
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    feature_id INTEGER REFERENCES feature_capabilities(id) ON DELETE SET NULL,

    -- Task definition
    title TEXT NOT NULL,
    description TEXT,

    -- Execution state
    status TEXT DEFAULT 'pending',      -- pending|running|paused|failed|completed
    current_criterion_id TEXT,          -- Which acceptance criterion being worked on

    -- Agent artifacts
    spec_content TEXT,                  -- Generated spec (for complex features)
    plan_content JSONB,                 -- Implementation plan as JSON
    progress_log TEXT,                  -- Append-only execution log
    error_message TEXT,                 -- Error details if failed

    -- Git integration
    branch_name TEXT,                   -- task/task-001-feature-slug
    commits TEXT[] DEFAULT '{}',        -- Array of commit SHAs
    pull_request_url TEXT,              -- GitHub PR URL when created

    -- Metrics
    total_sessions INTEGER DEFAULT 0,
    total_tokens_used INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_feature ON tasks(feature_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);
