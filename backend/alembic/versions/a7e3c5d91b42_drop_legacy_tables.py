"""Drop eight legacy tables no code reads or writes.

Dropped: artifacts, explorer_relationships, explorer_sub_elements,
sitemap_entries, task_labels, agent_sessions, user_prompts,
task_subtask_steps_archived. Owner approved 2026-10-10. Their rows were archived
first with pg_dump -Fc to
backups/table-archives/legacy-tables-20261010-221834.dump; restore data from
that file with pg_restore --data-only after a downgrade if it is ever needed.
None of these tables is referenced by another table.

Revision ID: a7e3c5d91b42
Revises: 9c4e2b107a63
"""

from alembic import op

revision = "a7e3c5d91b42"
down_revision = "9c4e2b107a63"
branch_labels = None
depends_on = None

_TABLES = (
    "artifacts",
    "explorer_relationships",
    "explorer_sub_elements",
    "sitemap_entries",
    "task_labels",
    "agent_sessions",
    "user_prompts",
    "task_subtask_steps_archived",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")


def downgrade() -> None:
    """Recreate the tables empty with their previous columns, keys and indexes."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_sessions (
            id SERIAL PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            session_id VARCHAR(50) NOT NULL,
            agent_type VARCHAR(50) NOT NULL,
            status VARCHAR(20) DEFAULT 'running',
            started_at TIMESTAMPTZ DEFAULT NOW(),
            ended_at TIMESTAMPTZ,
            capabilities_attempted TEXT[] DEFAULT '{}'::text[],
            capabilities_passed TEXT[] DEFAULT '{}'::text[],
            capabilities_failed TEXT[] DEFAULT '{}'::text[],
            tests_run INTEGER DEFAULT 0,
            tests_passed INTEGER DEFAULT 0,
            tests_failed INTEGER DEFAULT 0,
            notes TEXT,
            git_commit_sha VARCHAR(40),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            build_state JSONB DEFAULT '{}'::jsonb,
            UNIQUE (project_id, session_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_created ON agent_sessions (created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_project ON agent_sessions (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions (status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS artifacts (
            id SERIAL PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            artifact_id VARCHAR(50) NOT NULL,
            feature_id VARCHAR(20) NOT NULL,
            criterion_id VARCHAR(20),
            artifact_type VARCHAR(20) DEFAULT 'evidence',
            file_path VARCHAR(500) NOT NULL,
            file_size_bytes INTEGER,
            version INTEGER DEFAULT 1,
            is_current BOOLEAN DEFAULT TRUE,
            captured_at TIMESTAMPTZ DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            quality_status VARCHAR(20) DEFAULT 'pending',
            quality_issues JSONB DEFAULT '[]'::jsonb,
            confidence DOUBLE PRECISION,
            ai_reviewed_at TIMESTAMPTZ,
            ai_reviewed_by VARCHAR(50),
            ai_evidence TEXT,
            user_reviewed_at TIMESTAMPTZ,
            user_approved BOOLEAN,
            user_notes TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (project_id, artifact_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_criterion ON artifacts (criterion_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_current ON artifacts (is_current) WHERE is_current = TRUE")
    op.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_feature ON artifacts (feature_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_quality ON artifacts (quality_status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS explorer_relationships (
            id SERIAL PRIMARY KEY,
            project_id VARCHAR(50) NOT NULL,
            source_type VARCHAR(20) NOT NULL,
            source_path VARCHAR(500) NOT NULL,
            target_type VARCHAR(20) NOT NULL,
            target_path VARCHAR(500) NOT NULL,
            relationship VARCHAR(50) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (project_id, source_type, source_path, target_type, target_path, relationship)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_explorer_rel_source ON explorer_relationships (project_id, source_type, source_path)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_explorer_rel_target ON explorer_relationships (project_id, target_type, target_path)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS explorer_sub_elements (
            id SERIAL PRIMARY KEY,
            explorer_entry_id INTEGER NOT NULL REFERENCES explorer_entries(id) ON DELETE CASCADE,
            selector VARCHAR(500) NOT NULL,
            element_type VARCHAR(50) NOT NULL,
            label VARCHAR(200),
            discovered_at TIMESTAMPTZ DEFAULT NOW(),
            last_captured_at TIMESTAMPTZ,
            capture_count INTEGER DEFAULT 0,
            UNIQUE (explorer_entry_id, selector)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sub_elements_entry ON explorer_sub_elements (explorer_entry_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sub_elements_type ON explorer_sub_elements (element_type)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS sitemap_entries (
            id SERIAL PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            port INTEGER NOT NULL,
            path TEXT NOT NULL,
            method VARCHAR(10) DEFAULT 'GET',
            entry_type VARCHAR(20) NOT NULL,
            source VARCHAR(50),
            title TEXT,
            parent_path TEXT,
            health_status VARCHAR(20) DEFAULT 'unknown',
            console_errors INTEGER DEFAULT 0,
            console_warnings INTEGER DEFAULT 0,
            http_status INTEGER,
            response_time_ms INTEGER,
            last_error_message TEXT,
            last_checked_at TIMESTAMPTZ,
            discovered_at TIMESTAMPTZ DEFAULT NOW(),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (project_id, port, path, method)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_entry_type ON sitemap_entries (entry_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_health ON sitemap_entries (health_status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_last_checked ON sitemap_entries (last_checked_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_port ON sitemap_entries (port)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_project ON sitemap_entries (project_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS task_labels (
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (task_id, label)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_task_labels_label ON task_labels (label)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_task_labels_task ON task_labels (task_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS task_subtask_steps_archived (
            id SERIAL PRIMARY KEY,
            subtask_id TEXT NOT NULL REFERENCES task_subtasks(id) ON DELETE CASCADE,
            step_number INTEGER NOT NULL,
            description TEXT NOT NULL,
            passes BOOLEAN DEFAULT FALSE,
            passed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            spec JSONB,
            status VARCHAR(20) DEFAULT 'pending'
                CHECK (status IN ('pending', 'passed', 'failed', 'plan_defect')),
            fix_step_number INTEGER,
            UNIQUE (subtask_id, step_number)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_subtask_steps_passes ON task_subtask_steps_archived (passes)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_subtask_steps_subtask_id ON task_subtask_steps_archived (subtask_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_prompts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            session_id TEXT NOT NULL,
            prompt_number INTEGER NOT NULL,
            prompt_text TEXT NOT NULL,
            embedding vector(768),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (session_id, prompt_number)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_prompts_created ON user_prompts (project_id, created_at DESC)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_prompts_embedding ON user_prompts"
        " USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_prompts_project ON user_prompts (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_prompts_session ON user_prompts (session_id)")
