-- Migration 029: Add vector embedding columns for semantic search
-- Requires: pgvector extension (installed separately via: CREATE EXTENSION vector)

-- Add embedding column to observations
ALTER TABLE observations
ADD COLUMN IF NOT EXISTS embedding vector(768);

-- Add embedding column to learned_patterns
ALTER TABLE learned_patterns
ADD COLUMN IF NOT EXISTS embedding vector(768);

-- Create IVFFlat indexes for cosine similarity search
-- IVFFlat is faster for large datasets, uses lists parameter for clustering
-- Using 100 lists as recommended for datasets up to 1M rows
CREATE INDEX IF NOT EXISTS idx_observations_embedding
ON observations USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_learned_patterns_embedding
ON learned_patterns USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

COMMENT ON COLUMN observations.embedding IS 'Vector embedding (768 dims) for semantic search';
COMMENT ON COLUMN learned_patterns.embedding IS 'Vector embedding (768 dims) for semantic search';
