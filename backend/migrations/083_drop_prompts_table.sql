-- Migration 083: Drop prompts table
-- Prompts functionality moved to Agent Hub with markdown-based agent prompts
-- This table is no longer used

-- Drop the prompts table
DROP TABLE IF EXISTS prompts CASCADE;

-- Drop the index if it wasn't cascade dropped
DROP INDEX IF EXISTS prompts_project_idx;
