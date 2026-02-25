-- Migration 033: Unified acceptance criteria tables
-- Implements capability-centric TDD architecture with junction tables

-- Main acceptance criteria table
-- Stores reusable criteria that can be linked to capabilities or tasks
CREATE TABLE IF NOT EXISTS acceptance_criteria (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    criterion_id VARCHAR(20) NOT NULL,  -- Format: ac-NNN, generated per-project
    criterion TEXT NOT NULL,
    category VARCHAR(20) DEFAULT 'correctness',  -- performance, correctness, security, quality
    measurement VARCHAR(20) DEFAULT 'test',  -- test, metric, tool, manual
    threshold TEXT,  -- Specific value e.g., '<200ms', '100%'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by_task_id TEXT,  -- Optional: which task first defined this criterion

    UNIQUE (project_id, criterion_id)
);
-- Comment: criterion_id format is ac-NNN, generated via get_next_criterion_id()

-- Junction table: capability_criteria
-- Links criteria to capabilities (capability owns criteria)
CREATE TABLE IF NOT EXISTS capability_criteria (
    capability_id INTEGER NOT NULL REFERENCES capabilities(id) ON DELETE CASCADE,
    criterion_id INTEGER NOT NULL REFERENCES acceptance_criteria(id) ON DELETE CASCADE,

    PRIMARY KEY (capability_id, criterion_id)
);

-- Junction table: task_criteria
-- Links criteria to tasks with verification state
-- Used for standalone tasks OR to track which task verified which criterion
CREATE TABLE IF NOT EXISTS task_criteria (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    criterion_id INTEGER NOT NULL REFERENCES acceptance_criteria(id),
    verified BOOLEAN DEFAULT FALSE,
    verified_at TIMESTAMPTZ,
    verified_by VARCHAR(20),  -- opus, test, human, agent

    PRIMARY KEY (task_id, criterion_id),
    CONSTRAINT task_criteria_verified_by_check CHECK (
        verified_by IN ('opus', 'test', 'human', 'agent') OR verified_by IS NULL
    )
);

-- Junction table: criterion_tests
-- Links tests to criteria (replaces direct capability_tests relationship)
CREATE TABLE IF NOT EXISTS criterion_tests (
    criterion_id INTEGER NOT NULL REFERENCES acceptance_criteria(id) ON DELETE CASCADE,
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    is_primary BOOLEAN DEFAULT FALSE,  -- Primary test for this criterion
    added_at TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (criterion_id, test_id)
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_acceptance_criteria_project ON acceptance_criteria(project_id);
CREATE INDEX IF NOT EXISTS idx_capability_criteria_capability ON capability_criteria(capability_id);
CREATE INDEX IF NOT EXISTS idx_task_criteria_task ON task_criteria(task_id);
CREATE INDEX IF NOT EXISTS idx_criterion_tests_criterion ON criterion_tests(criterion_id);
