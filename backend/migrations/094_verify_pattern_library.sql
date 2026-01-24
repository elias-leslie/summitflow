-- Verify Pattern Library
-- Tracks verify_command outcomes to provide feedback during planning
-- and improve verification reliability over time.

CREATE TABLE IF NOT EXISTS verify_command_patterns (
    id SERIAL PRIMARY KEY,
    pattern_hash VARCHAR(64) NOT NULL UNIQUE,  -- SHA256 of normalized pattern
    normalized_pattern TEXT NOT NULL,           -- Pattern with IDs/paths stripped
    command_example TEXT NOT NULL,              -- One actual command example
    pattern_type VARCHAR(32),                   -- deploy, grep, curl, test, other
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    avg_duration_ms INTEGER DEFAULT 0,
    last_outcome_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookup by hash
CREATE INDEX IF NOT EXISTS idx_verify_patterns_hash ON verify_command_patterns(pattern_hash);

-- Index for pattern type filtering
CREATE INDEX IF NOT EXISTS idx_verify_patterns_type ON verify_command_patterns(pattern_type);

-- Index for finding high-success patterns
CREATE INDEX IF NOT EXISTS idx_verify_patterns_success ON verify_command_patterns(success_count DESC);

COMMENT ON TABLE verify_command_patterns IS 'Tracks verify_command execution outcomes for feedback loop';
COMMENT ON COLUMN verify_command_patterns.pattern_hash IS 'SHA256 hash of normalized_pattern for fast lookup';
COMMENT ON COLUMN verify_command_patterns.normalized_pattern IS 'Command pattern with task IDs, absolute paths, and ports normalized';
COMMENT ON COLUMN verify_command_patterns.pattern_type IS 'Category: deploy, grep, curl, test, other';
