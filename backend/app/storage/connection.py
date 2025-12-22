"""Database connection management."""

import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from dotenv import load_dotenv

# Load environment from ~/.env.local (same pattern as ~/.smbcredentials)
_env_file = Path.home() / ".env.local"
if _env_file.exists():
    load_dotenv(_env_file)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is required. "
        "Create ~/.env.local with DATABASE_URL=postgresql://..."
    )


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """Get a database connection.

    Usage:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    conn = psycopg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


def init_schema() -> None:
    """Initialize database schema."""
    with get_connection() as conn:
        with conn.cursor() as cur:
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

            # Sitemap health history
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sitemap_health_history (
                    id SERIAL PRIMARY KEY,
                    sitemap_entry_id INTEGER NOT NULL REFERENCES sitemap_entries(id) ON DELETE CASCADE,
                    checked_at TIMESTAMPTZ NOT NULL,
                    health_status VARCHAR(20),
                    console_errors INTEGER DEFAULT 0,
                    console_warnings INTEGER DEFAULT 0,
                    http_status INTEGER,
                    response_time_ms INTEGER,
                    error_details JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )

            # Indexes for sitemap_entries
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_project ON sitemap_entries(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_port ON sitemap_entries(port)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_health ON sitemap_entries(health_status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_entry_type ON sitemap_entries(entry_type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_last_checked ON sitemap_entries(last_checked_at)")

            # Indexes for sitemap_health_history
            cur.execute("CREATE INDEX IF NOT EXISTS idx_health_history_entry ON sitemap_health_history(sitemap_entry_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_health_history_checked ON sitemap_health_history(checked_at)")

            # ============================================================
            # Phase 3: Features, Vision, Artifacts Tables
            # ============================================================

            # Vision goals lookup table (must be before feature_capabilities due to FK)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS vision_goals (
                    code TEXT PRIMARY KEY,
                    project_id TEXT REFERENCES projects(id),
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_vision_goals_category ON vision_goals(category)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_vision_goals_project ON vision_goals(project_id)")

            # Vision goal details (objectives, features, success criteria)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS vision_goal_details (
                    id SERIAL PRIMARY KEY,
                    goal_code TEXT NOT NULL REFERENCES vision_goals(code) ON DELETE CASCADE,
                    detail_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    order_num INT DEFAULT 0,
                    metadata JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (goal_code, detail_type, order_num)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_vision_goal_details_code ON vision_goal_details(goal_code)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_vision_goal_details_type ON vision_goal_details(detail_type)")

            # Vision content (mission, vision, principles, roadmap)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS vision_content (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    content_type TEXT NOT NULL,
                    content_key TEXT NOT NULL,
                    title TEXT,
                    content TEXT NOT NULL,
                    order_num INT DEFAULT 0,
                    metadata JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (project_id, content_type, content_key)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_vision_content_project ON vision_content(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_vision_content_type ON vision_content(content_type)")

            # Feature capabilities - main features table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_capabilities (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    feature_id VARCHAR(20) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    category VARCHAR(100),
                    description TEXT,
                    passes BOOLEAN DEFAULT NULL,
                    task_file VARCHAR(255),
                    task_section VARCHAR(20),
                    health_status VARCHAR(20) DEFAULT 'active',
                    status VARCHAR(20) DEFAULT 'planned',
                    effort VARCHAR(10),
                    priority INTEGER DEFAULT 2,
                    verification_layers JSONB DEFAULT '[]'::jsonb,
                    layer_results JSONB DEFAULT '{}'::jsonb,
                    implementation_notes TEXT,
                    acceptance_criteria JSONB DEFAULT '[]'::jsonb,
                    vision_goals TEXT[] DEFAULT '{}',
                    last_verified_at TIMESTAMPTZ,
                    verified_by VARCHAR(50),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, feature_id)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_feature_project ON feature_capabilities(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_feature_category ON feature_capabilities(category)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_feature_passes ON feature_capabilities(passes)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_feature_status ON feature_capabilities(status)")

            # Feature tasks - subtasks for features
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_tasks (
                    id SERIAL PRIMARY KEY,
                    feature_id INTEGER NOT NULL REFERENCES feature_capabilities(id) ON DELETE CASCADE,
                    task_id VARCHAR(20) NOT NULL,
                    description TEXT NOT NULL,
                    completed BOOLEAN NOT NULL DEFAULT false,
                    order_num INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ,
                    completed_by VARCHAR(50),
                    files TEXT[],
                    notes TEXT,
                    status VARCHAR(20) DEFAULT 'pending',
                    effort VARCHAR(10),
                    task_type VARCHAR(20) DEFAULT 'implementation',
                    CONSTRAINT feature_tasks_unique_task UNIQUE (feature_id, task_id)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_feature_tasks_feature ON feature_tasks(feature_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_feature_tasks_completed ON feature_tasks(completed)")

            # Feature dependencies
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_dependencies (
                    id SERIAL PRIMARY KEY,
                    feature_id INTEGER NOT NULL REFERENCES feature_capabilities(id) ON DELETE CASCADE,
                    depends_on_id INTEGER NOT NULL REFERENCES feature_capabilities(id) ON DELETE CASCADE,
                    dependency_type TEXT NOT NULL DEFAULT 'blocks',
                    notes TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(feature_id, depends_on_id),
                    CHECK (feature_id != depends_on_id)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_feature_deps_feature ON feature_dependencies(feature_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_feature_deps_depends ON feature_dependencies(depends_on_id)")

            # Feature vision goal mappings (junction table)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_vision_goal_mappings (
                    id SERIAL PRIMARY KEY,
                    feature_id INT NOT NULL REFERENCES feature_capabilities(id) ON DELETE CASCADE,
                    vision_code TEXT NOT NULL REFERENCES vision_goals(code) ON DELETE CASCADE,
                    linked_at TIMESTAMPTZ DEFAULT NOW(),
                    linked_by VARCHAR(50),
                    UNIQUE (feature_id, vision_code)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_fvgm_feature ON feature_vision_goal_mappings(feature_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_fvgm_vision ON feature_vision_goal_mappings(vision_code)")

            # Artifacts - evidence storage for verification
            cur.execute(
                """
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
                    confidence FLOAT,
                    ai_reviewed_at TIMESTAMPTZ,
                    ai_reviewed_by VARCHAR(50),
                    ai_evidence TEXT,
                    user_reviewed_at TIMESTAMPTZ,
                    user_approved BOOLEAN,
                    user_notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, artifact_id)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_feature ON artifacts(feature_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_criterion ON artifacts(criterion_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_quality ON artifacts(quality_status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_current ON artifacts(is_current) WHERE is_current = TRUE")

            # Evidence table (same structure as artifacts, renamed for clarity)
            # Used by evidence_manager service
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    evidence_id VARCHAR(50) NOT NULL,
                    feature_id VARCHAR(20) NOT NULL,
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
            cur.execute("CREATE INDEX IF NOT EXISTS idx_evidence_feature ON evidence(feature_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_evidence_criterion ON evidence(criterion_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_evidence_quality ON evidence(quality_status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_evidence_current ON evidence(is_current) WHERE is_current = TRUE")

            # File audit table - stores file scan results per project
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS file_audit (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    path TEXT NOT NULL,
                    is_directory BOOLEAN NOT NULL DEFAULT FALSE,
                    extension VARCHAR(20),
                    size_bytes INTEGER DEFAULT 0,
                    lines_of_code INTEGER DEFAULT 0,
                    file_count INTEGER,
                    total_loc INTEGER,
                    bloat_level VARCHAR(20),
                    last_modified TIMESTAMPTZ,
                    last_commit_days INTEGER,
                    reference_count INTEGER DEFAULT 0,
                    stale_status VARCHAR(20),
                    scanned_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, path)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_file_audit_project ON file_audit(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_file_audit_path ON file_audit(path)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_file_audit_bloat ON file_audit(bloat_level) WHERE bloat_level IS NOT NULL")

            # ============================================================
            # Scanner Tables (Database, API, Celery introspection)
            # ============================================================

            # Database scanner - table introspection results
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS scanner_database (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    table_name VARCHAR(255) NOT NULL,
                    category VARCHAR(100),
                    row_count INTEGER DEFAULT 0,
                    total_columns INTEGER DEFAULT 0,
                    columns JSONB DEFAULT '[]',
                    columns_with_data JSONB DEFAULT '[]',
                    columns_mostly_null JSONB DEFAULT '[]',
                    completeness_pct INTEGER DEFAULT 0,
                    date_range_start DATE,
                    date_range_end DATE,
                    expected_freshness VARCHAR(20),
                    days_since_update INTEGER,
                    freshness_status VARCHAR(20),
                    health_status VARCHAR(20) DEFAULT 'unknown',
                    fk_referenced_by JSONB DEFAULT '[]',
                    last_scanned_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, table_name)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scanner_db_project ON scanner_database(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scanner_db_health ON scanner_database(health_status)")

            # API scanner - static route analysis results
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS scanner_api (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    endpoint_path VARCHAR(512) NOT NULL,
                    http_method VARCHAR(10) NOT NULL,
                    category VARCHAR(100),
                    route_file VARCHAR(255),
                    function_name VARCHAR(255),
                    depends_on_tables JSONB DEFAULT '[]',
                    frontend_callers JSONB DEFAULT '[]',
                    health_status VARCHAR(20) DEFAULT 'unknown',
                    last_scanned_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, endpoint_path, http_method)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scanner_api_project ON scanner_api(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scanner_api_health ON scanner_api(health_status)")

            # Celery scanner - task introspection results
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS scanner_celery (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    task_name VARCHAR(255) NOT NULL,
                    category VARCHAR(100),
                    task_path VARCHAR(512),
                    function_name VARCHAR(255),
                    schedule_description VARCHAR(255),
                    schedule_crontab VARCHAR(100),
                    schedule_interval_seconds INTEGER,
                    last_run_at TIMESTAMPTZ,
                    success_count_7d INTEGER DEFAULT 0,
                    failure_count_7d INTEGER DEFAULT 0,
                    success_rate_pct INTEGER,
                    populates_tables JSONB DEFAULT '[]',
                    reads_from_tables JSONB DEFAULT '[]',
                    depends_on_tasks JSONB DEFAULT '[]',
                    called_by JSONB DEFAULT '[]',
                    health_status VARCHAR(20) DEFAULT 'unknown',
                    last_scanned_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, task_name)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scanner_celery_project ON scanner_celery(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scanner_celery_health ON scanner_celery(health_status)")

            # ============================================================
            # Tasks Table - Agent execution state for features
            # ============================================================
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    feature_id INTEGER REFERENCES feature_capabilities(id) ON DELETE SET NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'pending',
                    current_criterion_id TEXT,
                    spec_content TEXT,
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
                    -- Issue tracking fields (beads migration)
                    priority INTEGER DEFAULT 2,
                    labels TEXT[] DEFAULT '{}',
                    task_type VARCHAR(20) DEFAULT 'task',
                    parent_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_feature ON tasks(feature_id)")
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
            cur.execute("CREATE INDEX IF NOT EXISTS idx_task_deps_depends ON task_dependencies(depends_on_task_id)")

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
            cur.execute("CREATE INDEX IF NOT EXISTS idx_capabilities_project ON capabilities(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_capabilities_component ON capabilities(component_id)")
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

            # Capability-Tests junction table (many-to-many)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_tests (
                    capability_id INTEGER NOT NULL REFERENCES capabilities(id) ON DELETE CASCADE,
                    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
                    is_primary BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (capability_id, test_id)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_capability_tests_capability ON capability_tests(capability_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_capability_tests_test ON capability_tests(test_id)")

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
                    claude_sdk_session_id TEXT,
                    gemini_sdk_session_id TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_roundtable_project ON roundtable_sessions(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_roundtable_created ON roundtable_sessions(created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_roundtable_updated ON roundtable_sessions(updated_at DESC)")

            # ============================================================
            # Extraction Prompts - Customizable prompts per project
            # ============================================================
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS extraction_prompts (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    prompt_type VARCHAR(50) NOT NULL,
                    prompt_text TEXT NOT NULL,
                    primary_agent VARCHAR(50) DEFAULT 'claude',
                    primary_model VARCHAR(100) DEFAULT 'claude-sonnet-4-5',
                    verification_enabled BOOLEAN DEFAULT FALSE,
                    verification_agent VARCHAR(50),
                    verification_model VARCHAR(100),
                    verification_prompt TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(project_id, prompt_type)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_extraction_prompts_project ON extraction_prompts(project_id)")

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
            cur.execute("CREATE INDEX IF NOT EXISTS idx_notification_project ON notifications(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_notification_status ON notifications(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_notification_created ON notifications(created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_notification_task ON notifications(task_id)")

            # Add new columns to existing tables if they don't exist
            # This allows running init_schema() on existing databases
            for column, table in [
                ("root_path TEXT", "projects"),
                ("backend_dir TEXT", "projects"),
                ("browser_scripts_dir TEXT", "projects"),
                ("data_dir TEXT", "projects"),
                # Issue tracking fields for tasks (beads migration)
                ("priority INTEGER DEFAULT 2", "tasks"),
                ("labels TEXT[] DEFAULT '{}'", "tasks"),
                ("task_type VARCHAR(20) DEFAULT 'task'", "tasks"),
                ("parent_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL", "tasks"),
                # Roundtable tools fields
                ("tools_enabled BOOLEAN DEFAULT TRUE", "roundtable_sessions"),
                ("write_enabled BOOLEAN DEFAULT FALSE", "roundtable_sessions"),
                ("yolo_mode BOOLEAN DEFAULT FALSE", "roundtable_sessions"),
                ("tool_stats JSONB DEFAULT '{\"total_calls\": 0, \"files_read\": 0, \"searches\": 0, \"writes\": 0}'::jsonb", "roundtable_sessions"),
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
                # Vision goals project scoping
                ("project_id TEXT REFERENCES projects(id)", "vision_goals"),
            ]:
                try:
                    col_name = column.split()[0]
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column}")
                except Exception:
                    pass  # Column already exists

            conn.commit()


if __name__ == "__main__":
    print("Initializing SummitFlow schema...")
    init_schema()
    print("Done!")
