-- Migration: 064_task_acceptance_criteria.sql
-- Purpose: Task-scoped acceptance criteria with verification routing
-- Created: 2026-01-16
-- Task: task-48ae552b (Normalize task schema)

-- Task-scoped acceptance criteria table
-- Replaces project-scoped acceptance_criteria for task-specific verification
CREATE TABLE IF NOT EXISTS task_acceptance_criteria (
    id SERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    criterion_id VARCHAR(10) NOT NULL,
    criterion TEXT NOT NULL,
    category VARCHAR(20) DEFAULT 'correctness' CHECK (category IN ('correctness', 'performance', 'security', 'quality')),
    verify_type VARCHAR(20) DEFAULT 'command' CHECK (verify_type IN ('command', 'api', 'browser', 'manual', 'none')),
    verify_by VARCHAR(10) DEFAULT 'test' CHECK (verify_by IN ('test', 'agent', 'human', 'opus')),
    verify_command TEXT,
    expected_output TEXT,
    verified BOOLEAN DEFAULT FALSE,
    verified_at TIMESTAMPTZ,
    verified_by_actual VARCHAR(20),
    display_order INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(task_id, criterion_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_task_ac_task_id ON task_acceptance_criteria(task_id);
CREATE INDEX IF NOT EXISTS idx_task_ac_verified ON task_acceptance_criteria(verified);
CREATE INDEX IF NOT EXISTS idx_task_ac_unverified ON task_acceptance_criteria(task_id) WHERE verified = FALSE;

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_task_ac_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS task_ac_updated_at ON task_acceptance_criteria;
CREATE TRIGGER task_ac_updated_at
    BEFORE UPDATE ON task_acceptance_criteria
    FOR EACH ROW
    EXECUTE FUNCTION update_task_ac_updated_at();

COMMENT ON TABLE task_acceptance_criteria IS 'Task-specific acceptance criteria with verification routing';
COMMENT ON COLUMN task_acceptance_criteria.criterion_id IS 'Short ID like ac-001, ac-002';
COMMENT ON COLUMN task_acceptance_criteria.verify_type IS 'command=bash, api=curl, browser=ba, manual=human, none=skip';
COMMENT ON COLUMN task_acceptance_criteria.verify_by IS 'Who/what performs verification: test|agent|human|opus';
COMMENT ON COLUMN task_acceptance_criteria.verified_by_actual IS 'Who actually performed the verification';
