-- Migration 086: Drop Evidence System
-- Part of task-bf5cf769: Task System Friction & Bypass Fixes
-- The Evidence system (~8K lines) is unused and replaced by mockups table

-- Drop tables in dependency order (children first)
DROP TABLE IF EXISTS evidence_regressions CASCADE;
DROP TABLE IF EXISTS evidence_capture_jobs CASCADE;
DROP TABLE IF EXISTS evidence CASCADE;
DROP TABLE IF EXISTS evidence_types CASCADE;
DROP TABLE IF EXISTS project_evidence_config CASCADE;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Dropped evidence system tables: evidence, evidence_regressions, evidence_capture_jobs, evidence_types, project_evidence_config';
END $$;
