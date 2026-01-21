-- Migration 087: Drop Tests System
-- Part of task-bf5cf769: Task System Friction & Bypass Fixes
-- The TDD Tests feature (~2.7K lines) is unused and being removed

-- Drop tables in dependency order (children first)
DROP TABLE IF EXISTS criterion_tests CASCADE;
DROP TABLE IF EXISTS test_runs CASCADE;
DROP TABLE IF EXISTS tests CASCADE;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Dropped tests system tables: tests, test_runs, criterion_tests';
END $$;
