"""Database schema initialization.

This module contains the init_schema() function which creates all database tables.
It was extracted from connection.py to separate schema concerns from connection management.
"""

import contextlib
import logging

import psycopg
from psycopg import sql

from .connection import get_connection

logger = logging.getLogger(__name__)

# PostgreSQL advisory lock ID for schema initialization
# Using a fixed hash to ensure all workers use the same lock
SCHEMA_INIT_LOCK_ID = 1234567890


def init_schema() -> None:
    """Initialize database schema.

    Uses PostgreSQL advisory lock to prevent race conditions when multiple
    workers start simultaneously.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Try to acquire advisory lock (non-blocking)
        cur.execute("SELECT pg_try_advisory_lock(%s)", (SCHEMA_INIT_LOCK_ID,))
        row = cur.fetchone()
        got_lock = row[0] if row else False

        if not got_lock:
            # Another worker is initializing, wait for them to finish
            logger.info("Schema initialization in progress by another worker, waiting...")
            cur.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_INIT_LOCK_ID,))
            # They're done, release our lock and return (schema already initialized)
            cur.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_INIT_LOCK_ID,))
            conn.commit()
            logger.info("Schema initialization completed by another worker")
            return

        try:
            _do_init_schema(conn, cur)
        finally:
            # Release the lock
            cur.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_INIT_LOCK_ID,))
            conn.commit()


def _do_init_schema(conn: psycopg.Connection, cur: psycopg.Cursor) -> None:
    """Actual schema initialization (called with advisory lock held)."""
    # Projects table (with config columns for verification engine)
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

    # Sitemap entries - scoped by project
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

    # Indexes for sitemap_entries
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_project ON sitemap_entries(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_port ON sitemap_entries(port)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_health ON sitemap_entries(health_status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_entry_type ON sitemap_entries(entry_type)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_sitemap_last_checked ON sitemap_entries(last_checked_at)"
    )

    # ============================================================
    # Tasks Table - Issue tracking and agent execution state
    # NOTE: Migrations are authoritative. This is fallback only.
    # ============================================================
    # Note: objective, spirit_anti, decisions, constraints, done_when moved to task_spirit (migration 072)
    # Note: labels moved to task_labels (migration 072)
    # Note: plan_content dropped (migration 072)
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
                pull_request_url TEXT,
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
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
    )
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

    # ============================================================
    # Task Dependencies - Dependency tracking between tasks
    # ============================================================
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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_task_deps_task ON task_dependencies(task_id)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_deps_depends ON task_dependencies(depends_on_task_id)"
    )

    # Agent sessions - Track agent build sessions
    cur.execute(
        """
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id SERIAL PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                session_id VARCHAR(50) NOT NULL,
                agent_type VARCHAR(50) NOT NULL,
                status VARCHAR(20) DEFAULT 'running',
                started_at TIMESTAMPTZ DEFAULT NOW(),
                ended_at TIMESTAMPTZ,
                -- Context tracking
                capabilities_attempted TEXT[] DEFAULT '{}',
                capabilities_passed TEXT[] DEFAULT '{}',
                capabilities_failed TEXT[] DEFAULT '{}',
                -- Stats
                tests_run INTEGER DEFAULT 0,
                tests_passed INTEGER DEFAULT 0,
                tests_failed INTEGER DEFAULT 0,
                -- Handoff
                notes TEXT,
                git_commit_sha VARCHAR(40),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(project_id, session_id)
            )
            """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_sessions_project ON agent_sessions(project_id)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_sessions_created ON agent_sessions(created_at DESC)"
    )

    # ============================================================
    # Project Agent Configuration - Default agents/models per project
    # ============================================================
    cur.execute(
        """
            CREATE TABLE IF NOT EXISTS project_agent_config (
                project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                primary_agent VARCHAR(50) DEFAULT 'claude',
                secondary_agent VARCHAR(50) DEFAULT 'gemini',
                primary_model VARCHAR(100) DEFAULT 'claude-sonnet-4-5',
                secondary_model VARCHAR(100) DEFAULT 'gemini-3-flash-preview',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
    )

    # ============================================================
    # Notifications table (for failure escalation alerts)
    # ============================================================
    cur.execute(
        """
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                user_email TEXT,
                idea_id TEXT,
                type VARCHAR(50) NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                severity VARCHAR(20) NOT NULL DEFAULT 'info',
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                read_at TIMESTAMPTZ,
                dismissed_at TIMESTAMPTZ
            )
            """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notification_project ON notifications(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notification_status ON notifications(status)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_created ON notifications(created_at DESC)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notification_task ON notifications(task_id)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_user_email ON notifications(user_email)"
    )

    # ============================================================
    # Design Standards Tables
    # ============================================================

    # Design standards - UI/UX standards with inheritance support
    cur.execute(
        """
            CREATE TABLE IF NOT EXISTS design_standards (
                id SERIAL PRIMARY KEY,
                project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                base_standard_id INTEGER REFERENCES design_standards(id) ON DELETE SET NULL,
                is_base BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(project_id, name)
            )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_standards_project ON design_standards(project_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_standards_base ON design_standards(is_base) WHERE is_base = TRUE"
    )

    # Design rules - Individual rules within a standard
    cur.execute(
        """
            CREATE TABLE IF NOT EXISTS design_rules (
                id SERIAL PRIMARY KEY,
                standard_id INTEGER NOT NULL REFERENCES design_standards(id) ON DELETE CASCADE,
                category VARCHAR(50) NOT NULL,
                rule_id VARCHAR(50) NOT NULL,
                name VARCHAR(200) NOT NULL,
                requirements JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(standard_id, rule_id)
            )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_design_rules_standard ON design_rules(standard_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_design_rules_category ON design_rules(category)")

    # ============================================================
    # Code Health Tables
    # ============================================================

    # Code health allow/block lists - for filtering false positives and known issues
    cur.execute(
        """
            CREATE TABLE IF NOT EXISTS code_health_lists (
                id SERIAL PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                list_type VARCHAR(20) NOT NULL CHECK (list_type IN ('allow', 'block')),
                category VARCHAR(50) NOT NULL,
                pattern TEXT NOT NULL,
                file_glob TEXT,
                reason TEXT,
                confidence FLOAT DEFAULT 1.0,
                source VARCHAR(50) DEFAULT 'manual',
                created_by VARCHAR(100),
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """
    )

    # Indexes for code_health_lists
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_code_health_project ON code_health_lists(project_id)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_code_health_type ON code_health_lists(list_type)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_code_health_category ON code_health_lists(category)"
    )
    # Unique constraint using COALESCE for nullable file_glob
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_code_health_unique
        ON code_health_lists(project_id, list_type, category, pattern, COALESCE(file_glob, ''))
        """
    )

    # ============================================================
    # Agent Performance Tracking
    # ============================================================

    # Individual records of model execution outcomes for performance analysis
    cur.execute(
        """
            CREATE TABLE IF NOT EXISTS model_performance_logs (
                id SERIAL PRIMARY KEY,
                task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
                model_name TEXT NOT NULL,
                task_type TEXT NOT NULL,
                complexity TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failure', 'error')),
                quality_score DOUBLE PRECISION,
                tokens_used INTEGER,
                latency_ms INTEGER,
                error_category TEXT,
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_model_perf_logs_lookup ON model_performance_logs(model_name, task_type, complexity)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_model_perf_logs_task_id ON model_performance_logs(task_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_model_perf_logs_created_at ON model_performance_logs(created_at DESC)")

    # Aggregated performance metrics for models, used for intelligent task routing
    cur.execute(
        """
            CREATE TABLE IF NOT EXISTS model_performance_metrics (
                model_name TEXT NOT NULL,
                task_type TEXT NOT NULL,
                complexity TEXT NOT NULL,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                total_executions INTEGER DEFAULT 0,
                avg_quality_score DOUBLE PRECISION DEFAULT 0.0,
                avg_latency_ms DOUBLE PRECISION DEFAULT 0.0,
                avg_tokens_used DOUBLE PRECISION DEFAULT 0.0,
                last_executed_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (model_name, task_type, complexity)
            )
        """
    )
    cur.execute(
        """
            CREATE INDEX IF NOT EXISTS idx_model_perf_metrics_ranking
            ON model_performance_metrics(task_type, complexity, success_count DESC, avg_quality_score DESC)
        """
    )

    # Add new columns to existing tables if they don't exist
    # This allows running init_schema() on existing databases
    for column, table in [
        ("root_path TEXT", "projects"),
        ("backend_dir TEXT", "projects"),
        ("browser_scripts_dir TEXT", "projects"),
        ("data_dir TEXT", "projects"),
        # TDD test configuration for projects
        (
            """test_config JSONB DEFAULT '{
                "backend_root": "backend",
                "frontend_root": "frontend",
                "pytest_path": ".venv/bin/pytest",
                "node_path": "npx",
                "test_patterns": {
                    "pytest": "tests/**/*.py",
                    "vitest": "**/*.test.{ts,tsx}"
                }
            }'::jsonb""",
            "projects",
        ),
        # Issue tracking fields for tasks (beads migration)
        ("priority INTEGER DEFAULT 2", "tasks"),
        # Note: labels moved to task_labels table in migration 072
        ("task_type VARCHAR(20) DEFAULT 'task'", "tasks"),
        ("parent_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL", "tasks"),
        # Note: spirit_anti, decisions, constraints, done_when moved to task_spirit table (migration 072)
        (
            "complexity VARCHAR(20) CHECK (complexity IN ('SIMPLE', 'STANDARD', 'COMPLEX'))",
            "tasks",
        ),
        # DEPRECATED: Subtask details column - superseded by step-level specs (migration 062)
        # Kept for backward compatibility but no longer populated by st import
        ("details JSONB", "task_subtasks"),
        # Step-level specs - implementation details per step, populated from plan.json (migration 062)
        ("spec JSONB", "task_subtask_steps"),
        # updated_at columns for tracking modifications (migration 077)
        ("updated_at TIMESTAMPTZ DEFAULT NOW()", "tasks"),
        ("updated_at TIMESTAMPTZ DEFAULT NOW()", "task_subtasks"),
        # escalation tracking for quality check results (migration 080)
        (
            "escalation_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL",
            "quality_check_results",
        ),
    ]:
        try:
            # Note: table and column names come from controlled internal list, not user input
            query = sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {}").format(
                sql.Identifier(table),
                sql.SQL(column),
            )
            cur.execute(query)
        except psycopg.errors.DuplicateColumn:
            pass  # Expected with IF NOT EXISTS on older PostgreSQL
        except Exception as e:
            # Log unexpected errors (type mismatches, constraint failures, etc.)
            column_name = column.split()[0]
            logger.warning("Failed to add column %s to %s: %s", column_name, table, e)

    # Create indexes for columns added via ALTER TABLE
    with contextlib.suppress(psycopg.errors.UndefinedColumn):
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_qcr_escalation_task_id
            ON quality_check_results(escalation_task_id)
            WHERE escalation_task_id IS NOT NULL
        """)

    conn.commit()


if __name__ == "__main__":
    print("Initializing SummitFlow schema...")
    init_schema()
    print("Done!")
