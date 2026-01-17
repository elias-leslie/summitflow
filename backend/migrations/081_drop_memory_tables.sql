-- Migration 081: Drop legacy memory system tables
-- Memory functionality moved to Agent Hub with Graphiti knowledge graph
-- These tables are no longer used

-- Drop tables in reverse dependency order
DROP TABLE IF EXISTS learned_patterns CASCADE;
DROP TABLE IF EXISTS session_diary CASCADE;
DROP TABLE IF EXISTS observations CASCADE;
DROP TABLE IF EXISTS observation_queue CASCADE;

-- Drop agent_checkpoints if it exists (from migration 011)
DROP TABLE IF EXISTS agent_checkpoints CASCADE;

-- Drop memory_config from projects if it exists (from migration 020)
ALTER TABLE projects DROP COLUMN IF EXISTS memory_config;
