"""Tests storage layer - Test registry CRUD operations.

This module provides data access for the centralized test registry.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from .connection import get_connection


def create_test(
    project_id: str,
    test_id: str,
    name: str,
    test_type: str,
    command: str | None = None,
    script: str | None = None,
    config: dict[str, Any] | None = None,
    working_dir: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Create a new test.

    Args:
        project_id: Project ID
        test_id: Unique test identifier
        name: Human-readable test name
        test_type: Type of test (pytest, mypy, ruff, vitest, api, ui)
        command: Command to run the test
        script: Script content for UI tests
        config: Additional configuration as JSON
        working_dir: Working directory for test execution
        timeout_seconds: Timeout in seconds (default 60)

    Returns:
        The created test dict with all columns.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tests (project_id, test_id, name, test_type, command, script,
                              config, working_dir, timeout_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, test_id, name, test_type, command, script,
                      config, working_dir, timeout_seconds, last_run_at, last_result,
                      last_duration_ms, last_output, last_error, run_count, pass_count,
                      fail_count, flaky_score, created_at, updated_at
            """,
            (
                project_id,
                test_id,
                name,
                test_type,
                command,
                script,
                json.dumps(config) if config else "{}",
                working_dir,
                timeout_seconds,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row)


def get_test(project_id: str, test_id: str) -> dict[str, Any] | None:
    """Get a test by project_id and test_id.

    Returns:
        Test dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, test_id, name, test_type, command, script,
                   config, working_dir, timeout_seconds, last_run_at, last_result,
                   last_duration_ms, last_output, last_error, run_count, pass_count,
                   fail_count, flaky_score, created_at, updated_at
            FROM tests
            WHERE project_id = %s AND test_id = %s
            """,
            (project_id, test_id),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def get_test_by_id(test_db_id: int) -> dict[str, Any] | None:
    """Get a test by database ID.

    Returns:
        Test dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, test_id, name, test_type, command, script,
                   config, working_dir, timeout_seconds, last_run_at, last_result,
                   last_duration_ms, last_output, last_error, run_count, pass_count,
                   fail_count, flaky_score, created_at, updated_at
            FROM tests
            WHERE id = %s
            """,
            (test_db_id,),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def list_tests(
    project_id: str,
    test_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List tests for a project, optionally filtered by type.

    Args:
        project_id: Project ID
        test_type: Optional test type to filter by
        limit: Maximum number of tests to return

    Returns:
        List of test dicts, ordered by type then name.
    """
    with get_connection() as conn, conn.cursor() as cur:
        if test_type is not None:
            cur.execute(
                """
                SELECT id, project_id, test_id, name, test_type, command, script,
                       config, working_dir, timeout_seconds, last_run_at, last_result,
                       last_duration_ms, last_output, last_error, run_count, pass_count,
                       fail_count, flaky_score, created_at, updated_at
                FROM tests
                WHERE project_id = %s AND test_type = %s
                ORDER BY name ASC
                LIMIT %s
                """,
                (project_id, test_type, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, test_id, name, test_type, command, script,
                       config, working_dir, timeout_seconds, last_run_at, last_result,
                       last_duration_ms, last_output, last_error, run_count, pass_count,
                       fail_count, flaky_score, created_at, updated_at
                FROM tests
                WHERE project_id = %s
                ORDER BY test_type ASC, name ASC
                LIMIT %s
                """,
                (project_id, limit),
            )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def update_test(
    project_id: str,
    test_id: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Update a test.

    Args:
        project_id: Project ID
        test_id: Test ID
        **kwargs: Fields to update (name, test_type, command, script, config,
                  working_dir, timeout_seconds)

    Returns:
        Updated test dict or None if not found.
    """
    allowed_fields = {
        "name",
        "test_type",
        "command",
        "script",
        "config",
        "working_dir",
        "timeout_seconds",
    }
    updates = {}
    for k, v in kwargs.items():
        if k in allowed_fields:
            if k == "config" and isinstance(v, dict):
                updates[k] = json.dumps(v)
            else:
                updates[k] = v

    if not updates:
        return get_test(project_id, test_id)

    # Always update updated_at
    updates["updated_at"] = datetime.now(UTC).isoformat()

    set_clauses = [sql.SQL("{} = %s").format(sql.Identifier(k)) for k in updates]
    values = [*list(updates.values()), project_id, test_id]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            UPDATE tests
            SET {set_clause}
            WHERE project_id = %s AND test_id = %s
            RETURNING id, project_id, test_id, name, test_type, command, script,
                      config, working_dir, timeout_seconds, last_run_at, last_result,
                      last_duration_ms, last_output, last_error, run_count, pass_count,
                      fail_count, flaky_score, created_at, updated_at
            """).format(set_clause=sql.SQL(", ").join(set_clauses)),
            values,
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def update_test_result(
    project_id: str,
    test_id: str,
    result: str,
    duration_ms: int,
    output: str | None = None,
    error: str | None = None,
) -> dict[str, Any] | None:
    """Update a test with execution results.

    Updates last_* fields and increments run/pass/fail counts.
    Also recalculates flaky_score.

    Args:
        project_id: Project ID
        test_id: Test ID
        result: Test result ('passed', 'failed', 'error', 'timeout')
        duration_ms: Execution duration in milliseconds
        output: Test output (truncated if necessary)
        error: Error message if failed

    Returns:
        Updated test dict or None if not found.
    """
    now = datetime.now(UTC)

    # Determine count increments
    pass_increment = 1 if result == "passed" else 0
    fail_increment = 1 if result in ("failed", "error", "timeout") else 0

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE tests
            SET last_run_at = %s,
                last_result = %s,
                last_duration_ms = %s,
                last_output = %s,
                last_error = %s,
                run_count = run_count + 1,
                pass_count = pass_count + %s,
                fail_count = fail_count + %s,
                flaky_score = CASE
                    WHEN run_count >= 5 THEN
                        CAST(fail_count + %s AS FLOAT) / CAST(run_count + 1 AS FLOAT)
                    ELSE flaky_score
                END,
                updated_at = %s
            WHERE project_id = %s AND test_id = %s
            RETURNING id, project_id, test_id, name, test_type, command, script,
                      config, working_dir, timeout_seconds, last_run_at, last_result,
                      last_duration_ms, last_output, last_error, run_count, pass_count,
                      fail_count, flaky_score, created_at, updated_at
            """,
            (
                now,
                result,
                duration_ms,
                output,
                error,
                pass_increment,
                fail_increment,
                fail_increment,
                now,
                project_id,
                test_id,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def delete_test(project_id: str, test_id: str) -> bool:
    """Delete a test.

    Returns:
        True if deleted, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM tests
            WHERE project_id = %s AND test_id = %s
            RETURNING id
            """,
            (project_id, test_id),
        )
        deleted = cur.fetchone() is not None
        conn.commit()

    return deleted


def _row_to_dict(row: tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a dict."""
    if row is None:
        return {}

    return {
        "id": row[0],
        "project_id": row[1],
        "test_id": row[2],
        "name": row[3],
        "test_type": row[4],
        "command": row[5],
        "script": row[6],
        "config": row[7] if isinstance(row[7], dict) else json.loads(row[7] or "{}"),
        "working_dir": row[8],
        "timeout_seconds": row[9],
        "last_run_at": row[10].isoformat() if row[10] else None,
        "last_result": row[11],
        "last_duration_ms": row[12],
        "last_output": row[13],
        "last_error": row[14],
        "run_count": row[15],
        "pass_count": row[16],
        "fail_count": row[17],
        "flaky_score": row[18],
        "created_at": row[19].isoformat() if row[19] else None,
        "updated_at": row[20].isoformat() if row[20] else None,
    }
