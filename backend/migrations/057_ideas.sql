-- Ideas table for crowdsourced game improvements
-- Used by Monkey Fight and other projects with crowdsourcing enabled

CREATE TABLE IF NOT EXISTS ideas (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    raw_text TEXT NOT NULL,
    refined_text TEXT,
    user_email TEXT,
    status TEXT NOT NULL DEFAULT 'pending_refinement',
    -- pending_refinement, refined, approved, rejected, executing, completed, failed
    category TEXT,  -- bug, feature, content, enhancement
    complexity TEXT,  -- simple, medium, complex
    feasibility_score REAL,
    rejection_reason TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    -- Priority scoring
    ease_score REAL,
    impact_score REAL,
    priority_score REAL,  -- ROI = impact/ease
    -- Linking
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ideas_project ON ideas(project_id);
CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status);
CREATE INDEX IF NOT EXISTS idx_ideas_user ON ideas(user_email);
CREATE INDEX IF NOT EXISTS idx_ideas_priority ON ideas(priority_score DESC NULLS LAST);
