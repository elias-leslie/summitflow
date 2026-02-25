-- Migration 016: Add raw_excerpt column to observations
-- Purpose: Store verbatim excerpt from tool output for future embedding quality
-- The raw excerpt captures the original context without summarization

ALTER TABLE observations ADD COLUMN IF NOT EXISTS raw_excerpt TEXT;

COMMENT ON COLUMN observations.raw_excerpt IS 'Verbatim excerpt from tool output (max 2000 chars) for future embedding generation';
