"""Schema migrations - backward compatibility column additions.

This module handles ALTER TABLE operations to add columns that were introduced
after initial schema creation. This allows init_schema() to work on existing databases.

Note: Alembic migrations are authoritative. This is fallback only.
"""

import contextlib

import psycopg
from psycopg import sql

from ...logging_config import get_logger
from .._sql import static_sql

logger = get_logger(__name__)


def apply_schema_migrations(conn: psycopg.Connection, cur: psycopg.Cursor) -> None:
    """Apply schema migrations for backward compatibility.

    Adds columns to existing tables if they don't exist, allowing init_schema()
    to be run on databases that were created before these columns were added.
    """
    _create_task_related_tables(cur)
    _add_missing_columns(cur)
    _drop_removed_spirit_columns(cur)
    _drop_removed_design_review_tables(cur)
    _create_design_vote_tables(cur)
    _backfill_execution_mode(cur)
    _ensure_execution_mode_constraint(cur)
    _create_migration_indexes(cur)
    conn.commit()


def _create_task_related_tables(cur: psycopg.Cursor) -> None:
    """Create task-related tables that were originally from archived SQL migrations.

    These tables are not in the core tables module because they were added by
    SQL migrations (072-series) that predated the tables/ module system.
    """
    _create_task_spirit_table(cur)
    _create_task_subtask_tables(cur)
    _create_task_labels_table(cur)
    _create_task_table_indexes(cur)


def _create_task_spirit_table(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_spirit (
            task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
            done_when JSONB DEFAULT '[]'::jsonb,
            context JSONB DEFAULT '{}'::jsonb,
            plan_status VARCHAR DEFAULT 'draft',
            plan_approved_at TIMESTAMPTZ,
            plan_approved_by TEXT,
            plan_history JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            complexity VARCHAR
        )
        """
    )


def _create_task_subtask_tables(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_subtasks (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            subtask_id TEXT NOT NULL,
            phase TEXT,
            description TEXT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            passes BOOLEAN DEFAULT FALSE,
            passed_at TIMESTAMPTZ,
            citations_acknowledged_at TIMESTAMPTZ,
            subtask_type TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(task_id, subtask_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_subtask_steps (
            id SERIAL PRIMARY KEY,
            subtask_id TEXT NOT NULL REFERENCES task_subtasks(id) ON DELETE CASCADE,
            step_number INTEGER NOT NULL,
            description TEXT NOT NULL,
            passes BOOLEAN DEFAULT FALSE,
            spec JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(subtask_id, step_number)
        )
        """
    )


def _create_task_labels_table(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_labels (
            id SERIAL PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(task_id, label)
        )
        """
    )


def _create_task_table_indexes(cur: psycopg.Cursor) -> None:
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_spirit_complexity"
        " ON task_spirit(complexity)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_spirit_plan_status"
        " ON task_spirit(plan_status)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_subtasks_task"
        " ON task_subtasks(task_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_labels_task"
        " ON task_labels(task_id)"
    )


def _drop_removed_spirit_columns(cur: psycopg.Cursor) -> None:
    """Drop spirit columns removed by Alembic migration 52f2ce12774b.

    Handles test databases and older schemas that still have the old columns.
    """
    for col in ("objective", "spirit_anti", "decisions", "constraints"):
        with contextlib.suppress(psycopg.errors.UndefinedColumn, psycopg.errors.UndefinedTable):
            cur.execute(
                sql.SQL("ALTER TABLE task_spirit DROP COLUMN IF EXISTS {}").format(
                    sql.Identifier(col)
                )
            )


def _drop_removed_design_review_tables(cur: psycopg.Cursor) -> None:
    """Drop the removed global/live design review persistence tables."""
    for table in (
        "collab_connector_pairings",
        "collab_evidence_packets",
        "collab_annotations",
        "collab_participants",
        "collab_audit_events",
        "collab_sessions",
        "route_evidence",
    ):
        with contextlib.suppress(psycopg.Error):
            cur.execute(
                sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                    sql.Identifier(table)
                )
            )


def _create_design_vote_tables(cur: psycopg.Cursor) -> None:
    """Create cumulative design/mockup vote tables for legacy schemas."""
    with contextlib.suppress(psycopg.errors.UndefinedTable):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS design_asset_votes (
                id BIGSERIAL PRIMARY KEY,
                asset_id INTEGER NOT NULL REFERENCES design_assets(id) ON DELETE CASCADE,
                vote VARCHAR(10) NOT NULL CHECK (vote IN ('up', 'down')),
                voter_email TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_design_asset_votes_asset "
            "ON design_asset_votes(asset_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_design_asset_votes_vote "
            "ON design_asset_votes(asset_id, vote)"
        )
    with contextlib.suppress(psycopg.errors.UndefinedTable):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS mockup_votes (
                id BIGSERIAL PRIMARY KEY,
                mockup_id INTEGER NOT NULL REFERENCES mockups(id) ON DELETE CASCADE,
                vote VARCHAR(10) NOT NULL CHECK (vote IN ('up', 'down')),
                voter_email TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_mockup_votes_mockup "
            "ON mockup_votes(mockup_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_mockup_votes_vote "
            "ON mockup_votes(mockup_id, vote)"
        )


def _project_column_additions() -> list[tuple[str, str]]:
    """Return column additions for the projects table."""
    return [
        ("root_path TEXT", "projects"),
        ("public_url TEXT", "projects"),
        ("backend_dir TEXT", "projects"),
        ("browser_scripts_dir TEXT", "projects"),
        ("data_dir TEXT", "projects"),
        (
            "category TEXT NOT NULL DEFAULT 'dev' CHECK (category IN ('production', 'testing', 'dev'))",
            "projects",
        ),
        (
            "sidebar_rank INTEGER CHECK (sidebar_rank IS NULL OR sidebar_rank >= 0)",
            "projects",
        ),
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
    ]


def _task_column_additions() -> list[tuple[str, str]]:
    """Return column additions for the tasks and related tables."""
    return [
        # Issue tracking fields for tasks (beads migration)
        ("priority INTEGER DEFAULT 2", "tasks"),
        ("task_type VARCHAR(20) DEFAULT 'task'", "tasks"),
        ("parent_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL", "tasks"),
        ("capability_id INTEGER", "tasks"),
        ("feature_id INTEGER", "tasks"),
        (
            "complexity VARCHAR(20) CHECK (complexity IN ('SIMPLE', 'STANDARD', 'COMPLEX'))",
            "tasks",
        ),
        # Step-level specs - implementation details per step, populated from plan.json
        ("spec JSONB", "task_subtask_steps"),
        # updated_at columns for tracking modifications
        ("updated_at TIMESTAMPTZ DEFAULT NOW()", "tasks"),
        ("updated_at TIMESTAMPTZ DEFAULT NOW()", "task_subtasks"),
        # Escalation tracking for quality check results
        (
            "escalation_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL",
            "quality_check_results",
        ),
        # Agent Hub session tracking
        ("agent_hub_session_ids TEXT[] DEFAULT '{}'::text[]", "tasks"),
        # Subtask type for agent routing (v2 autocode)
        ("subtask_type TEXT", "task_subtasks"),
        # Labels array for task categorization
        ("labels TEXT[] DEFAULT '{}'::text[]", "tasks"),
        (
            "execution_mode VARCHAR(20) DEFAULT 'manual' CHECK (execution_mode IN ('manual', 'autonomous', 'manual_only'))",
            "tasks",
        ),
        # AI review results
        ("ai_review JSONB", "tasks"),
        # Git conflict handling (migration 52bde0e4709d)
        ("conflict_info JSONB", "tasks"),
        ("merge_sha TEXT", "tasks"),
        ("build_state JSONB DEFAULT '{}'::jsonb", "agent_sessions"),
    ]


def _backup_source_column_additions() -> list[tuple[str, str]]:
    """Return column additions for the backup_sources table."""
    return [
        ("storage_backend_id TEXT", "backup_sources"),
        ("last_restore_tested_at TIMESTAMPTZ", "backup_sources"),
        ("last_restore_test_ok BOOLEAN", "backup_sources"),
        ("last_restore_test_error TEXT", "backup_sources"),
        ("last_drill_at TIMESTAMPTZ", "backup_sources"),
        ("last_drill_ok BOOLEAN", "backup_sources"),
        ("last_drill_backup_id TEXT", "backup_sources"),
        ("last_drill_result JSONB", "backup_sources"),
    ]


def _mockup_column_additions() -> list[tuple[str, str]]:
    """Return column additions for mockup artifacts."""
    return [
        ("metadata JSONB NOT NULL DEFAULT '{}'::jsonb", "mockups"),
    ]


def _add_missing_columns(cur: psycopg.Cursor) -> None:
    """Add columns that may be missing from older schema versions."""
    column_additions = (
        _project_column_additions()
        + _task_column_additions()
        + _backup_source_column_additions()
        + _mockup_column_additions()
    )
    for column, table in column_additions:
        _try_add_column(cur, table, column)


def _try_add_column(cur: psycopg.Cursor, table: str, column: str) -> None:
    """Try to add a column to a table, ignoring errors if it already exists.

    Uses a SAVEPOINT so that a failed ALTER TABLE doesn't abort the entire
    transaction — allowing subsequent column additions to proceed.

    Args:
        cur: Database cursor
        table: Table name (from controlled internal list)
        column: Column definition SQL (from controlled internal list)
    """
    column_name = column.split()[0]
    savepoint = f"sp_add_{table}_{column_name}"
    try:
        cur.execute(sql.SQL("SAVEPOINT {}").format(sql.Identifier(savepoint)))
        # Note: table and column names come from controlled internal list, not user input
        query = sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {}").format(
            sql.Identifier(table),
            static_sql(column),
        )
        cur.execute(query)
        cur.execute(sql.SQL("RELEASE SAVEPOINT {}").format(sql.Identifier(savepoint)))
    except psycopg.errors.DuplicateColumn:
        # Expected with IF NOT EXISTS on older PostgreSQL versions
        cur.execute(sql.SQL("ROLLBACK TO SAVEPOINT {}").format(sql.Identifier(savepoint)))
    except Exception as e:
        # Rollback to savepoint so the transaction can continue
        cur.execute(sql.SQL("ROLLBACK TO SAVEPOINT {}").format(sql.Identifier(savepoint)))
        logger.warning("Failed to add column %s to %s: %s", column_name, table, e)


def _create_migration_indexes(cur: psycopg.Cursor) -> None:
    """Create indexes for columns added via migrations."""
    _create_escalation_index(cur)
    _create_tasks_indexes(cur)
    _create_misc_indexes(cur)


def _create_escalation_index(cur: psycopg.Cursor) -> None:
    with contextlib.suppress(psycopg.errors.UndefinedColumn):
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_qcr_escalation_task_id
            ON quality_check_results(escalation_task_id)
            WHERE escalation_task_id IS NOT NULL
            """
        )


def _create_tasks_indexes(cur: psycopg.Cursor) -> None:
    with contextlib.suppress(psycopg.errors.UndefinedColumn):
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_capability ON tasks(capability_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_feature ON tasks(feature_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC)")


def _create_misc_indexes(cur: psycopg.Cursor) -> None:
    with contextlib.suppress(psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn):
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_events_trace_timestamp ON events(trace_id, "timestamp" ASC)'
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_qcr_project_created"
            " ON quality_check_results(project_id, created_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_qcr_project_type_created"
            " ON quality_check_results(project_id, check_type, created_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_qa_issues_project_status_detected"
            " ON qa_issues(project_id, status, last_detected_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_backups_project_event_time"
            " ON backups(project_id, COALESCE(completed_at, created_at) DESC)"
            " WHERE status IN ('completed', 'failed')"
        )


def _backfill_execution_mode(cur: psycopg.Cursor) -> None:
    """Default any null execution_mode to manual; the `autonomous` boolean column was
    dropped in migration a9c4e1b7d2e8, so derived backfill from that column is gone."""
    cur.execute(
        """
        UPDATE tasks
        SET execution_mode = 'manual'
        WHERE execution_mode IS NULL
        """
    )


def _ensure_execution_mode_constraint(cur: psycopg.Cursor) -> None:
    """Expand legacy execution_mode checks to include manual_only."""
    with contextlib.suppress(psycopg.errors.UndefinedTable):
        cur.execute(
            """
            ALTER TABLE tasks
            DROP CONSTRAINT IF EXISTS tasks_execution_mode_check
            """
        )
        cur.execute(
            """
            ALTER TABLE tasks
            DROP CONSTRAINT IF EXISTS ck_tasks_execution_mode
            """
        )
        cur.execute(
            """
            ALTER TABLE tasks
            ADD CONSTRAINT ck_tasks_execution_mode
            CHECK (execution_mode IN ('manual', 'autonomous', 'manual_only'))
            """
        )
