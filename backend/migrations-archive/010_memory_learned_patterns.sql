-- Migration 010: Create learned_patterns table
-- Pattern storage with full lifecycle management

CREATE TABLE IF NOT EXISTS learned_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id TEXT NOT NULL REFERENCES projects(id),

    -- Pattern content
    pattern_type TEXT NOT NULL,  -- 'code', 'workflow', 'preference', 'constraint'
    title TEXT NOT NULL,
    content TEXT NOT NULL,  -- Max 150 chars enforced at application level
    rationale TEXT,  -- Why this pattern was suggested

    -- Source tracking
    source_diary_ids JSONB DEFAULT '[]',  -- Diary entries that led to this pattern
    source_observation_ids JSONB DEFAULT '[]',  -- Observations that led to this pattern

    -- Lifecycle action
    action TEXT NOT NULL DEFAULT 'add',  -- 'add', 'update', 'remove', 'merge'
    target_pattern_id UUID REFERENCES learned_patterns(id),  -- For update/merge actions

    -- Status workflow
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'approved', 'rejected', 'applied', 'removed'
    confidence DECIMAL(3,2),  -- 0.00 to 1.00

    -- Usage tracking
    usage_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    superseded_by UUID REFERENCES learned_patterns(id),  -- For tracking pattern evolution

    -- Application tracking
    applied_to_rules_at TIMESTAMPTZ,  -- When written to .claude/rules/

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT  -- 'auto' or user identifier

    -- Note: UNIQUE constraint added separately to allow partial index
);

-- Prevent duplicate active patterns
CREATE UNIQUE INDEX IF NOT EXISTS idx_learned_patterns_unique_title
ON learned_patterns(project_id, title)
WHERE status NOT IN ('removed', 'rejected');

-- Query indexes
CREATE INDEX IF NOT EXISTS idx_learned_patterns_project_status
ON learned_patterns(project_id, status);

CREATE INDEX IF NOT EXISTS idx_learned_patterns_project_used
ON learned_patterns(project_id, last_used_at DESC);

-- Stale patterns: applied but not used in 30+ days
CREATE INDEX IF NOT EXISTS idx_learned_patterns_stale
ON learned_patterns(project_id, last_used_at)
WHERE status = 'applied' AND last_used_at IS NOT NULL;

COMMENT ON TABLE learned_patterns IS 'Learned patterns with full lifecycle management';
