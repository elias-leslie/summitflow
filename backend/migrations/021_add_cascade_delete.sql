-- Migration 021: Add CASCADE DELETE for memory tables
-- When a project is deleted, all related memory data should be deleted automatically

-- Drop existing foreign key constraints and recreate with CASCADE DELETE

-- observation_queue.project_id
ALTER TABLE observation_queue
    DROP CONSTRAINT IF EXISTS observation_queue_project_id_fkey;
ALTER TABLE observation_queue
    ADD CONSTRAINT observation_queue_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

-- observations.project_id
ALTER TABLE observations
    DROP CONSTRAINT IF EXISTS observations_project_id_fkey;
ALTER TABLE observations
    ADD CONSTRAINT observations_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

-- session_diary.project_id
ALTER TABLE session_diary
    DROP CONSTRAINT IF EXISTS session_diary_project_id_fkey;
ALTER TABLE session_diary
    ADD CONSTRAINT session_diary_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

-- learned_patterns.project_id
ALTER TABLE learned_patterns
    DROP CONSTRAINT IF EXISTS learned_patterns_project_id_fkey;
ALTER TABLE learned_patterns
    ADD CONSTRAINT learned_patterns_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

-- agent_checkpoints.project_id
ALTER TABLE agent_checkpoints
    DROP CONSTRAINT IF EXISTS agent_checkpoints_project_id_fkey;
ALTER TABLE agent_checkpoints
    ADD CONSTRAINT agent_checkpoints_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
