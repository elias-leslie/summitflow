"""Database schema initialization.

This module contains the init_schema() function which creates all database tables.
It was extracted from connection.py to separate schema concerns from connection management.
"""

import logging

import psycopg
from psycopg import sql

from .connection import get_connection

logger = logging.getLogger(__name__)


def init_schema() -> None:
    """Initialize database schema."""
    with get_connection() as conn, conn.cursor() as cur:
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
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sitemap_health ON sitemap_entries(health_status)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sitemap_entry_type ON sitemap_entries(entry_type)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sitemap_last_checked ON sitemap_entries(last_checked_at)"
        )

        # ============================================================
        # Evidence Tables
        # ============================================================

        # Evidence table - evidence storage for verification
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS evidence (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    evidence_id VARCHAR(50) NOT NULL,
                    capability_id VARCHAR(50) NOT NULL,
                    criterion_id VARCHAR(20),
                    evidence_type VARCHAR(20) DEFAULT 'evidence',
                    file_path VARCHAR(500) NOT NULL,
                    file_size_bytes INTEGER,
                    version INTEGER DEFAULT 1,
                    is_current BOOLEAN DEFAULT TRUE,
                    captured_at TIMESTAMPTZ DEFAULT NOW(),
                    expires_at TIMESTAMPTZ,
                    quality_status VARCHAR(20) DEFAULT 'pending',
                    quality_issues JSONB DEFAULT '[]'::jsonb,
                    confidence FLOAT,
                    ai_reviewed_at TIMESTAMPTZ,
                    ai_reviewed_by VARCHAR(50),
                    ai_evidence TEXT,
                    user_reviewed_at TIMESTAMPTZ,
                    user_approved BOOLEAN,
                    user_notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, evidence_id)
                )
                """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_evidence_project ON evidence(project_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_evidence_capability ON evidence(capability_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_evidence_criterion ON evidence(criterion_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_evidence_quality ON evidence(quality_status)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_evidence_current ON evidence(is_current) WHERE is_current = TRUE"
        )

        # ============================================================
        # Tasks Table - Issue tracking and agent execution state
        # NOTE: Migrations are authoritative. This is fallback only.
        # ============================================================
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'pending',
                    plan_content JSONB,
                    progress_log TEXT,
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
                    labels TEXT[] DEFAULT '{}',
                    task_type VARCHAR(20) DEFAULT 'task',
                    parent_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                    -- TDD linkage
                    capability_id INTEGER REFERENCES capabilities(id) ON DELETE SET NULL,
                    -- Autonomous execution fields
                    claimed_by TEXT,
                    claimed_at TIMESTAMPTZ,
                    lock_expires_at TIMESTAMPTZ,
                    tier INTEGER,
                    pre_merge_sha TEXT,
                    review_result JSONB,
                    -- AI agent reliability fields
                    objective TEXT,
                    current_phase TEXT,
                    verification_result JSONB,
                    -- AI enrichment fields
                    raw_request TEXT,
                    enrichment_status TEXT,
                    enriched_by TEXT,
                    enriched_at TIMESTAMPTZ
                )
                """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id)")

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

        # ============================================================
        # TDD Architecture Tables - Components, Capabilities, Tests
        # ============================================================

        # Components - Major parts of the system (3-8 per project)
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS components (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    component_id VARCHAR(50) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    priority INTEGER DEFAULT 2,
                    status VARCHAR(20) DEFAULT 'planned',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, component_id)
                )
                """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_components_project ON components(project_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_components_status ON components(status)")

        # Capabilities - What must work (5-15 per component)
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS capabilities (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    component_id INTEGER NOT NULL REFERENCES components(id) ON DELETE CASCADE,
                    capability_id VARCHAR(50) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    priority INTEGER DEFAULT 2,
                    status VARCHAR(20) DEFAULT 'pending',
                    locked_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, capability_id)
                )
                """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_capabilities_project ON capabilities(project_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_capabilities_component ON capabilities(component_id)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_capabilities_status ON capabilities(status)")

        # Tests - Centralized test registry (how we verify)
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS tests (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    test_id VARCHAR(100) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    test_type VARCHAR(50) NOT NULL,
                    command TEXT,
                    script TEXT,
                    config JSONB DEFAULT '{}'::jsonb,
                    working_dir TEXT,
                    timeout_seconds INTEGER DEFAULT 60,
                    -- Result tracking
                    last_run_at TIMESTAMPTZ,
                    last_result VARCHAR(20),
                    last_duration_ms INTEGER,
                    last_output TEXT,
                    last_error TEXT,
                    -- Statistics
                    run_count INTEGER DEFAULT 0,
                    pass_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    flaky_score FLOAT DEFAULT 0.0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, test_id)
                )
                """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tests_project ON tests(project_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tests_type ON tests(test_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tests_result ON tests(last_result)")

        # ============================================================
        # Unified Criteria Tables (TDD Architecture)
        # ============================================================

        # Acceptance criteria - reusable criteria linked to capabilities or tasks
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS acceptance_criteria (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    criterion_id VARCHAR(20) NOT NULL,
                    criterion TEXT NOT NULL,
                    category VARCHAR(20) DEFAULT 'correctness',
                    measurement VARCHAR(20) DEFAULT 'test',
                    threshold TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by_task_id TEXT,
                    UNIQUE (project_id, criterion_id)
                )
                """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_acceptance_criteria_project ON acceptance_criteria(project_id)"
        )

        # Capability-Criteria junction (capability owns criteria)
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS capability_criteria (
                    capability_id INTEGER NOT NULL REFERENCES capabilities(id) ON DELETE CASCADE,
                    criterion_id INTEGER NOT NULL REFERENCES acceptance_criteria(id) ON DELETE CASCADE,
                    PRIMARY KEY (capability_id, criterion_id)
                )
                """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_capability_criteria_capability ON capability_criteria(capability_id)"
        )

        # Task-Criteria junction (standalone or verification tracking)
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS task_criteria (
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    criterion_id INTEGER NOT NULL REFERENCES acceptance_criteria(id),
                    verified BOOLEAN DEFAULT FALSE,
                    verified_at TIMESTAMPTZ,
                    verified_by VARCHAR(20),
                    PRIMARY KEY (task_id, criterion_id),
                    CONSTRAINT task_criteria_verified_by_check CHECK (
                        verified_by IN ('opus', 'test', 'human', 'agent') OR verified_by IS NULL
                    )
                )
                """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_task_criteria_task ON task_criteria(task_id)")

        # Criterion-Tests junction (tests verify criteria)
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS criterion_tests (
                    criterion_id INTEGER NOT NULL REFERENCES acceptance_criteria(id) ON DELETE CASCADE,
                    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
                    is_primary BOOLEAN DEFAULT FALSE,
                    added_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (criterion_id, test_id)
                )
                """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_criterion_tests_criterion ON criterion_tests(criterion_id)"
        )

        # NOTE: capability_tests table REMOVED in migration 035
        # Tests are now linked to capabilities via criterion_tests junction table:
        #   capability -> capability_criteria -> acceptance_criteria -> criterion_tests -> test

        # Test runs - Historical test execution records
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS test_runs (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
                    run_type VARCHAR(20) NOT NULL DEFAULT 'manual',
                    result VARCHAR(20) NOT NULL,
                    duration_ms INTEGER,
                    output TEXT,
                    error TEXT,
                    evidence_path TEXT,
                    triggered_by VARCHAR(100),
                    session_id TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_test_runs_project ON test_runs(project_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_test_runs_test ON test_runs(test_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_test_runs_result ON test_runs(result)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_test_runs_created ON test_runs(created_at DESC)"
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
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_sessions_created ON agent_sessions(created_at DESC)"
        )

        # Accepted specs - Permanent storage for accepted spec definitions
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS accepted_specs (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    spec_json JSONB NOT NULL,
                    accepted_at TIMESTAMPTZ DEFAULT NOW(),
                    accepted_by VARCHAR(50),
                    notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_accepted_specs_project ON accepted_specs(project_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_accepted_specs_accepted ON accepted_specs(accepted_at DESC)"
        )

        # ============================================================
        # Roundtable Sessions - Multi-agent chat persistence
        # ============================================================
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS roundtable_sessions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title VARCHAR(255),
                    description TEXT,
                    status VARCHAR(20) DEFAULT 'active',
                    agent_mode VARCHAR(20) DEFAULT 'both',
                    mode VARCHAR(20) NOT NULL DEFAULT 'quick',
                    tools_enabled BOOLEAN DEFAULT TRUE,
                    tool_stats JSONB DEFAULT '{"total_calls": 0, "files_read": 0, "searches": 0}'::jsonb,
                    messages JSONB DEFAULT '[]'::jsonb,
                    generated_features JSONB DEFAULT '[]'::jsonb,
                    generated_spec JSONB DEFAULT NULL,
                    claude_sdk_session_id TEXT,
                    gemini_sdk_session_id TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_roundtable_project ON roundtable_sessions(project_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_roundtable_created ON roundtable_sessions(created_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_roundtable_updated ON roundtable_sessions(updated_at DESC)"
        )

        # ============================================================
        # Prompts - Customizable prompts per project (spec, recovery, qa, extraction)
        # ============================================================
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS prompts (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    prompt_type VARCHAR(50) NOT NULL,
                    prompt_text TEXT NOT NULL,
                    primary_agent VARCHAR(50) DEFAULT 'claude',
                    primary_model VARCHAR(100) DEFAULT 'claude-sonnet-4-5',
                    category VARCHAR(50) DEFAULT 'extraction',
                    thinking_budget INTEGER DEFAULT 0,
                    tools_enabled TEXT[],
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, prompt_type)
                )
                """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS prompts_project_idx ON prompts(project_id)")

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
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_notification_project ON notifications(project_id)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_notification_status ON notifications(status)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_notification_created ON notifications(created_at DESC)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_notification_task ON notifications(task_id)")

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
            ("labels TEXT[] DEFAULT '{}'", "tasks"),
            ("task_type VARCHAR(20) DEFAULT 'task'", "tasks"),
            ("parent_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL", "tasks"),
            # Roundtable tools fields
            ("tools_enabled BOOLEAN DEFAULT TRUE", "roundtable_sessions"),
            ("write_enabled BOOLEAN DEFAULT FALSE", "roundtable_sessions"),
            ("yolo_mode BOOLEAN DEFAULT FALSE", "roundtable_sessions"),
            (
                'tool_stats JSONB DEFAULT \'{"total_calls": 0, "files_read": 0, "searches": 0, "writes": 0}\'::jsonb',
                "roundtable_sessions",
            ),
            # Agent config override for per-session customization
            ("agent_override VARCHAR(50)", "roundtable_sessions"),
            ("model_override VARCHAR(100)", "roundtable_sessions"),
            # Roundtable session enhancements (SDK sessions, multi-session)
            ("title VARCHAR(255)", "roundtable_sessions"),
            ("description TEXT", "roundtable_sessions"),
            ("status VARCHAR(20) DEFAULT 'active'", "roundtable_sessions"),
            ("agent_mode VARCHAR(20) DEFAULT 'both'", "roundtable_sessions"),
            ("claude_sdk_session_id TEXT", "roundtable_sessions"),
            ("gemini_sdk_session_id TEXT", "roundtable_sessions"),
            # TDD spec generation - ephemeral working storage during roundtable
            ("generated_spec JSONB", "roundtable_sessions"),
            # TDD capability linkage - link tasks to capabilities instead of features
            ("capability_id INTEGER REFERENCES capabilities(id) ON DELETE SET NULL", "tasks"),
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

        conn.commit()


if __name__ == "__main__":
    print("Initializing SummitFlow schema...")
    init_schema()
    print("Done!")
