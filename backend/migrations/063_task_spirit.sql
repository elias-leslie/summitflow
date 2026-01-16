-- Migration: 063_task_spirit.sql
-- Purpose: Create task_spirit table for agent guidance + plan approval workflow
-- Created: 2026-01-16
-- Task: task-48ae552b (Normalize task schema)

-- task_spirit: 1:1 with tasks. Consolidates agent guidance + plan approval workflow.
-- plan_status gates execution start via trigger.
CREATE TABLE IF NOT EXISTS task_spirit (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    objective TEXT NOT NULL,
    spirit_anti TEXT,
    decisions JSONB DEFAULT '[]',
    constraints JSONB DEFAULT '[]',
    done_when JSONB DEFAULT '[]',
    context JSONB DEFAULT '{}',
    plan_status VARCHAR(20) DEFAULT 'draft' CHECK (plan_status IN ('draft', 'pending_review', 'approved', 'rejected')),
    plan_approved_at TIMESTAMPTZ,
    plan_approved_by TEXT,
    plan_history JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for plan status queries (find unapproved tasks)
CREATE INDEX IF NOT EXISTS idx_task_spirit_plan_status ON task_spirit(plan_status);

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_task_spirit_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS task_spirit_updated_at ON task_spirit;
CREATE TRIGGER task_spirit_updated_at
    BEFORE UPDATE ON task_spirit
    FOR EACH ROW
    EXECUTE FUNCTION update_task_spirit_updated_at();

COMMENT ON TABLE task_spirit IS 'Agent guidance and plan approval workflow. 1:1 with tasks.';
COMMENT ON COLUMN task_spirit.objective IS 'What the task aims to achieve (from plan.json)';
COMMENT ON COLUMN task_spirit.spirit_anti IS 'What to avoid during implementation (anti-patterns)';
COMMENT ON COLUMN task_spirit.decisions IS 'JSONB array of architectural/design decisions';
COMMENT ON COLUMN task_spirit.constraints IS 'JSONB array of implementation constraints';
COMMENT ON COLUMN task_spirit.done_when IS 'JSONB array of completion criteria';
COMMENT ON COLUMN task_spirit.context IS 'JSONB blob for plan.json context field (round-trip preservation)';
COMMENT ON COLUMN task_spirit.plan_status IS 'draft|pending_review|approved|rejected - gates execution';
COMMENT ON COLUMN task_spirit.plan_history IS 'JSONB array of {status, timestamp, actor, notes} transitions';
