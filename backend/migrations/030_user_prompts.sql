-- Migration 030: Create user_prompts table for capturing user prompts
-- Used for semantic search across user queries

CREATE TABLE IF NOT EXISTS user_prompts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    prompt_number INTEGER NOT NULL,
    prompt_text TEXT NOT NULL,
    embedding vector(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Each session has unique prompt numbers
    UNIQUE(session_id, prompt_number)
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_user_prompts_project ON user_prompts(project_id);
CREATE INDEX IF NOT EXISTS idx_user_prompts_session ON user_prompts(session_id);
CREATE INDEX IF NOT EXISTS idx_user_prompts_created ON user_prompts(project_id, created_at DESC);

-- IVFFlat index for semantic search on embeddings
CREATE INDEX IF NOT EXISTS idx_user_prompts_embedding
ON user_prompts USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

COMMENT ON TABLE user_prompts IS 'User prompts captured for semantic search and context';
COMMENT ON COLUMN user_prompts.prompt_number IS 'Sequential prompt number within a session';
COMMENT ON COLUMN user_prompts.embedding IS 'Vector embedding (768 dims) for semantic search';
