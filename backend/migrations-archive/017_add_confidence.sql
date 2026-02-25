-- Migration 017: Add confidence column to observations
-- Purpose: LLM-assigned confidence score for retrieval ranking
-- Range: 0.00 to 1.00 (higher = more confident extraction)

ALTER TABLE observations ADD COLUMN IF NOT EXISTS confidence DECIMAL(3,2) DEFAULT 0.50;

-- Index for confidence-based queries (e.g., retrieve high-confidence observations first)
CREATE INDEX IF NOT EXISTS idx_observations_confidence ON observations(confidence DESC);

COMMENT ON COLUMN observations.confidence IS 'LLM confidence score (0.00-1.00) for extraction quality';
