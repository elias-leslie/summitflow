"""Schema migrations - backward compatibility column additions.

This module handles ALTER TABLE operations to add columns that were introduced
after initial schema creation. This allows init_schema() to work on existing databases.

Note: Alembic migrations are authoritative. This is fallback only.
"""

import contextlib
import logging

import psycopg
from psycopg import sql

logger = logging.getLogger(__name__)


def apply_schema_migrations(conn: psycopg.Connection, cur: psycopg.Cursor) -> None:
    """Apply schema migrations for backward compatibility.

    Adds columns to existing tables if they don't exist, allowing init_schema()
    to be run on databases that were created before these columns were added.
    """
    _add_missing_columns(cur)
    _create_migration_indexes(cur)
    conn.commit()


def _project_column_additions() -> list[tuple[str, str]]:
    """Return column additions for the projects table."""
    return [
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
    ]


def _task_column_additions() -> list[tuple[str, str]]:
    """Return column additions for the tasks and related tables."""
    return [
        # Issue tracking fields for tasks (beads migration)
        ("priority INTEGER DEFAULT 2", "tasks"),
        ("task_type VARCHAR(20) DEFAULT 'task'", "tasks"),
        ("parent_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL", "tasks"),
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
        # AI review results
        ("ai_review JSONB", "tasks"),
        # Git conflict handling (migration 52bde0e4709d)
        ("conflict_info JSONB", "tasks"),
        ("merge_sha TEXT", "tasks"),
    ]


def _add_missing_columns(cur: psycopg.Cursor) -> None:
    """Add columns that may be missing from older schema versions."""
    column_additions = _project_column_additions() + _task_column_additions()
    for column, table in column_additions:
        _try_add_column(cur, table, column)


def _try_add_column(cur: psycopg.Cursor, table: str, column: str) -> None:
    """Try to add a column to a table, ignoring errors if it already exists.

    Args:
        cur: Database cursor
        table: Table name (from controlled internal list)
        column: Column definition SQL (from controlled internal list)
    """
    try:
        # Note: table and column names come from controlled internal list, not user input
        query = sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {}").format(
            sql.Identifier(table),
            sql.SQL(column),
        )
        cur.execute(query)
    except psycopg.errors.DuplicateColumn:
        # Expected with IF NOT EXISTS on older PostgreSQL versions
        pass
    except Exception as e:
        # Log unexpected errors (type mismatches, constraint failures, etc.)
        column_name = column.split()[0]
        logger.warning("Failed to add column %s to %s: %s", column_name, table, e)


def _create_migration_indexes(cur: psycopg.Cursor) -> None:
    """Create indexes for columns added via migrations.

    Suppresses errors if the referenced columns don't exist (e.g., in fresh databases
    where quality_check_results table hasn't been created yet).
    """
    with contextlib.suppress(psycopg.errors.UndefinedColumn):
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_qcr_escalation_task_id
            ON quality_check_results(escalation_task_id)
            WHERE escalation_task_id IS NOT NULL
            """
        )
