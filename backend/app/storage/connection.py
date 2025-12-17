"""Database connection management."""

import os
from contextlib import contextmanager
from typing import Generator

import psycopg


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://portfolio_ai_user:portfolio_ai_dev_2025@localhost:5432/summitflow",
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
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_vision_goals_category ON vision_goals(category)")

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

            # Add new columns to existing tables if they don't exist
            # This allows running init_schema() on existing databases
            for column, table in [
                ("root_path TEXT", "projects"),
                ("backend_dir TEXT", "projects"),
                ("browser_scripts_dir TEXT", "projects"),
                ("data_dir TEXT", "projects"),
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
