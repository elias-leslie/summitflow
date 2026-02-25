-- Migration 104: Drop ideas table (consolidated into task system)
-- Ideas now created as tasks directly via /tasks/from-ideation with label "crowdsourced"

-- Drop FKs first
ALTER TABLE ideas DROP CONSTRAINT IF EXISTS ideas_project_id_fkey;
ALTER TABLE ideas DROP CONSTRAINT IF EXISTS ideas_task_id_fkey;

-- Drop the table
DROP TABLE IF EXISTS ideas;

-- Remove idea_id from notifications (no longer referenced)
ALTER TABLE notifications DROP COLUMN IF EXISTS idea_id;
