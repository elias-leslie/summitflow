-- Migration: Make learned_patterns.project_id nullable for global patterns
-- This removes the need for a fake "_global_" project entry

BEGIN;

-- 1. Drop the existing FK constraint
ALTER TABLE learned_patterns DROP CONSTRAINT learned_patterns_project_id_fkey;

-- 2. Make project_id nullable
ALTER TABLE learned_patterns ALTER COLUMN project_id DROP NOT NULL;

-- 3. Update global patterns to use NULL instead of '_global_'
UPDATE learned_patterns SET project_id = NULL WHERE project_id = '_global_';

-- 4. Re-add FK constraint (now allows NULL)
ALTER TABLE learned_patterns
  ADD CONSTRAINT learned_patterns_project_id_fkey
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

-- 5. Delete the fake _global_ project
DELETE FROM projects WHERE id = '_global_';

COMMIT;
