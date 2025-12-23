-- Add build_state column to agent_sessions for recovery system tracking
-- Migration: 024_agent_sessions_build_state.sql

ALTER TABLE agent_sessions 
ADD COLUMN IF NOT EXISTS build_state JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN agent_sessions.build_state IS 'JSON state for build recovery: attempt_history, good_commits, current_strategy';
