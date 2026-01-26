-- Migration: Add subtask_citations table for tracking episode usage with ratings
-- Purpose: Track which memory episodes were loaded/cited during subtask execution
--          with three-signal rating (used/helpful/harmful)

CREATE TABLE subtask_citations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subtask_id TEXT NOT NULL,
    episode_uuid TEXT NOT NULL,
    rating TEXT NOT NULL CHECK (rating IN ('used', 'helpful', 'harmful')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (subtask_id) REFERENCES task_subtasks(id) ON DELETE CASCADE
);

CREATE INDEX idx_subtask_citations_subtask ON subtask_citations(subtask_id);
CREATE INDEX idx_subtask_citations_episode ON subtask_citations(episode_uuid);
CREATE INDEX idx_subtask_citations_rating ON subtask_citations(rating);
