"""Core tables: projects, sitemap_entries, tasks, task_dependencies."""

import psycopg


def create_core_tables(cur: psycopg.Cursor) -> None:
    """Create core tables and their indexes."""
    _create_projects_table(cur)
    _create_sitemap_entries_table(cur)
    _create_tasks_table(cur)
    _create_task_dependencies_table(cur)


def _create_projects_table(cur: psycopg.Cursor) -> None:
    """Create projects table."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            base_url TEXT NOT NULL,
            health_endpoint TEXT DEFAULT '/health',
            frontend_port INTEGER DEFAULT 3000,
            backend_port INTEGER DEFAULT 8000,
            root_path TEXT,
            backend_dir TEXT,
            browser_scripts_dir TEXT,
            data_dir TEXT,
            agent_configs JSONB DEFAULT '{
                "claude_enabled": true,
                "gemini_enabled": true,
                "default_agent": "gemini",
                "claude_model": "claude-sonnet-4-5",
                "gemini_model": "gemini-3-flash-preview"
            }'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )


def _create_sitemap_entries_table(cur: psycopg.Cursor) -> None:
    """Create sitemap_entries table and indexes."""
    cur.execute(
        """
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
            UNIQUE(project_id, port, path, method)
        )
        """
    )

    # Create indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_project ON sitemap_entries(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_port ON sitemap_entries(port)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_health ON sitemap_entries(health_status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_entry_type ON sitemap_entries(entry_type)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_sitemap_last_checked ON sitemap_entries(last_checked_at)"
    )


def _create_tasks_table(cur: psycopg.Cursor) -> None:
    """Create tasks table and indexes.

    Note: Migrations are authoritative. This is fallback only.
    Some fields have been moved to other tables (task_spirit, task_labels) in migration 072.
    """
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            branch_name TEXT,
            commits TEXT[] DEFAULT '{}',
            total_sessions INTEGER DEFAULT 0,
            total_tokens_used INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            -- Issue tracking fields
            priority INTEGER DEFAULT 2,
            task_type VARCHAR(20) DEFAULT 'task',
            parent_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
            -- Autonomous execution fields
            claimed_by TEXT,
            claimed_at TIMESTAMPTZ,
            lock_expires_at TIMESTAMPTZ,
            tier INTEGER,
            pre_merge_sha TEXT,
            review_result JSONB,
            -- Complexity (still on tasks table)
            complexity VARCHAR(20) CHECK (complexity IN ('SIMPLE', 'STANDARD', 'COMPLEX')),
            current_phase TEXT,
            verification_result JSONB,
            -- AI enrichment fields
            raw_request TEXT,
            enrichment_status TEXT,
            enriched_by TEXT,
            enriched_at TIMESTAMPTZ,
            -- Autonomous execution mode
            autonomous BOOLEAN DEFAULT FALSE,
            agent_override VARCHAR(50),
            agent_hub_session_ids TEXT[] DEFAULT '{}',
            labels TEXT[] DEFAULT '{}',
            ai_review JSONB,
            conflict_info JSONB,
            merge_sha TEXT,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )

    # Create indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id)")
    # Composite indexes for common query patterns (PERF-002, PERF-004)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_project_created ON tasks(project_id, created_at DESC)"
    )


def _create_task_dependencies_table(cur: psycopg.Cursor) -> None:
    """Create task_dependencies table and indexes."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_dependencies (
            id SERIAL PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            depends_on_task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            dependency_type VARCHAR(20) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(task_id, depends_on_task_id, dependency_type)
        )
        """
    )

    # Create indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_task_deps_task ON task_dependencies(task_id)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_deps_depends ON task_dependencies(depends_on_task_id)"
    )
