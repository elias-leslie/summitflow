-- Migration 082: Drop context_access_log table
-- Part of legacy memory cleanup (task-c5c5f682)
-- This table tracked memory pattern expansions, no longer used with Graphiti

DROP TABLE IF EXISTS context_access_log CASCADE;
