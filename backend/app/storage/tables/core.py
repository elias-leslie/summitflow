"""Core tables: projects, sitemap_entries, tasks, task_dependencies."""

import psycopg


def create_core_tables(cur: psycopg.Cursor) -> None:
    """Create core tables and their indexes."""
    _create_projects_table(cur)
    _create_access_tables(cur)
    _create_sitemap_entries_table(cur)
    _create_tasks_table(cur)
    _create_task_deletions_table(cur)
    _create_task_dependencies_table(cur)
    _create_maintenance_runs_table(cur)
    _create_runtime_metric_samples_table(cur)


def _create_projects_table(cur: psycopg.Cursor) -> None:
    """Create projects table."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            base_url TEXT NOT NULL,
            public_url TEXT,
            health_endpoint TEXT DEFAULT '/health',
            frontend_port INTEGER DEFAULT 3000,
            backend_port INTEGER DEFAULT 8000,
            root_path TEXT,
            backend_dir TEXT,
            browser_scripts_dir TEXT,
            data_dir TEXT,
            category TEXT NOT NULL DEFAULT 'dev'
                CHECK (category IN ('production', 'testing', 'dev')),
            sidebar_rank INTEGER
                CHECK (sidebar_rank IS NULL OR sidebar_rank >= 0),
            agent_configs JSONB DEFAULT '{
                "claude_enabled": true,
                "gemini_enabled": true,
                "default_agent": "gemini"
            }'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )


def _create_access_tables(cur: psycopg.Cursor) -> None:
    """Create in-app access control tables."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS share_users (
            email TEXT PRIMARY KEY,
            role TEXT NOT NULL CHECK (role IN ('owner', 'viewer')),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS share_grants (
            id BIGSERIAL PRIMARY KEY,
            user_email TEXT NOT NULL REFERENCES share_users(email) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            section TEXT NOT NULL CHECK (section IN ('design')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_email, project_id, section)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_share_grants_user ON share_grants(user_email)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_share_grants_project ON share_grants(project_id)"
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
            capability_id INTEGER,  -- intentionally denormalized; no capabilities table exists
            feature_id INTEGER,     -- intentionally denormalized; no features table exists
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
            -- Autonomous execution mode (canonical; the legacy `autonomous`
            -- boolean was dropped in migration a9c4e1b7d2e8 and is now derived).
            execution_mode VARCHAR(20) DEFAULT 'manual'
                CHECK (execution_mode IN ('manual', 'autonomous', 'manual_only')),
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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_capability ON tasks(capability_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_feature ON tasks(feature_id)")
    # Composite indexes for common query patterns (PERF-002, PERF-004)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_project_created ON tasks(project_id, created_at DESC)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC)")


def _create_task_deletions_table(cur: psycopg.Cursor) -> None:
    """Create archived task deletion snapshots for forensic retrieval."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_deletions (
            id BIGSERIAL PRIMARY KEY,
            task_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deletion_source TEXT NOT NULL DEFAULT 'unknown',
            deletion_reason TEXT,
            snapshot JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_deletions_task_id_deleted_at"
        " ON task_deletions(task_id, deleted_at DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_deletions_project_id"
        " ON task_deletions(project_id)"
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


def _create_maintenance_runs_table(cur: psycopg.Cursor) -> None:
    """Create maintenance_runs table and indexes."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_runs (
            id BIGSERIAL PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            duration_ms INTEGER,
            rows_cleaned INTEGER NOT NULL DEFAULT 0,
            summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_maintenance_runs_workflow_started"
        " ON maintenance_runs(workflow_name, started_at DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_maintenance_runs_status_started"
        " ON maintenance_runs(status, started_at DESC)"
    )


def _create_runtime_metric_samples_table(cur: psycopg.Cursor) -> None:
    """Create runtime service resource metric samples."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_metric_samples (
            id BIGSERIAL PRIMARY KEY,
            sampled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sample_bucket TIMESTAMPTZ NOT NULL,
            service TEXT NOT NULL,
            display_name TEXT NOT NULL,
            manager TEXT NOT NULL,
            category TEXT NOT NULL,
            state TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '',
            source_name TEXT NOT NULL DEFAULT '',
            cpu_percent DOUBLE PRECISION,
            memory_percent DOUBLE PRECISION,
            memory_used_bytes BIGINT,
            memory_limit_bytes BIGINT,
            raw_mem_usage TEXT,
            net_io TEXT,
            block_io TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(service, sample_bucket)
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_metric_samples_service_sampled"
        " ON runtime_metric_samples(service, sampled_at DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_metric_samples_sampled"
        " ON runtime_metric_samples(sampled_at DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_metric_samples_manager_category"
        " ON runtime_metric_samples(manager, category, sampled_at DESC)"
    )
