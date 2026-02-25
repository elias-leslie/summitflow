-- Migration 022: Add content hash column for observation deduplication
-- Prevents duplicate observations from same tool execution in same session

-- Add content_hash column to observations table
ALTER TABLE observations
    ADD COLUMN IF NOT EXISTS content_hash TEXT;

-- Create index for efficient deduplication lookups
-- Index on (session_id, content_hash, created_at) for checking duplicates within time window
CREATE INDEX IF NOT EXISTS idx_observations_dedup
    ON observations(session_id, content_hash, created_at)
    WHERE content_hash IS NOT NULL;
