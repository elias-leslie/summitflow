-- Migration 031: Add granular embedding columns to observations
-- Separate embeddings for narrative and title enable more precise semantic search

-- Add embedding column for narrative (main content)
ALTER TABLE observations
ADD COLUMN IF NOT EXISTS embedding_narrative vector(768);

-- Add embedding column for title (concise identifier)
ALTER TABLE observations
ADD COLUMN IF NOT EXISTS embedding_title vector(768);

-- Create IVFFlat indexes for cosine similarity search
CREATE INDEX IF NOT EXISTS idx_observations_embedding_narrative
ON observations USING ivfflat (embedding_narrative vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_observations_embedding_title
ON observations USING ivfflat (embedding_title vector_cosine_ops) WITH (lists = 100);

COMMENT ON COLUMN observations.embedding_narrative IS 'Vector embedding (768 dims) for narrative content';
COMMENT ON COLUMN observations.embedding_title IS 'Vector embedding (768 dims) for title';
