-- Migration: 065_subtask_dependencies.sql
-- Purpose: Track dependencies between subtasks (DAG structure)
-- Created: 2026-01-16
-- Task: task-48ae552b (Normalize task schema)

-- Subtask dependencies junction table
-- Enables DAG representation of subtask execution order
CREATE TABLE IF NOT EXISTS subtask_dependencies (
    id SERIAL PRIMARY KEY,
    subtask_id TEXT NOT NULL REFERENCES task_subtasks(id) ON DELETE CASCADE,
    depends_on_subtask_id TEXT NOT NULL REFERENCES task_subtasks(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(subtask_id, depends_on_subtask_id),
    CHECK (subtask_id != depends_on_subtask_id)
);

-- Indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_subtask_deps_subtask ON subtask_dependencies(subtask_id);
CREATE INDEX IF NOT EXISTS idx_subtask_deps_depends ON subtask_dependencies(depends_on_subtask_id);

-- Trigger to prevent circular dependencies
CREATE OR REPLACE FUNCTION check_subtask_dependency_cycle()
RETURNS TRIGGER AS $$
DECLARE
    cycle_detected BOOLEAN;
BEGIN
    -- Check for cycle using recursive CTE
    WITH RECURSIVE dependency_chain AS (
        -- Start from the dependency we're about to add
        SELECT NEW.depends_on_subtask_id AS subtask_id, 1 AS depth
        UNION ALL
        -- Follow the chain backwards
        SELECT sd.depends_on_subtask_id, dc.depth + 1
        FROM subtask_dependencies sd
        JOIN dependency_chain dc ON sd.subtask_id = dc.subtask_id
        WHERE dc.depth < 100  -- Prevent infinite loops
    )
    SELECT EXISTS (
        SELECT 1 FROM dependency_chain WHERE subtask_id = NEW.subtask_id
    ) INTO cycle_detected;

    IF cycle_detected THEN
        RAISE EXCEPTION 'Circular dependency detected: % -> % would create cycle',
            NEW.subtask_id, NEW.depends_on_subtask_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS check_subtask_dep_cycle ON subtask_dependencies;
CREATE TRIGGER check_subtask_dep_cycle
    BEFORE INSERT OR UPDATE ON subtask_dependencies
    FOR EACH ROW
    EXECUTE FUNCTION check_subtask_dependency_cycle();

COMMENT ON TABLE subtask_dependencies IS 'DAG of subtask execution order. subtask_id depends on depends_on_subtask_id.';
