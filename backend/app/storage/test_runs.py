"""Test runs storage layer - Test execution history.

This module provides data access for test run history and statistics.
"""

from __future__ import annotations

from typing import Any

from .connection import get_connection


def create_test_run(
    project_id: str,
    test_db_id: int,
    run_type: str,
    result: str,
    duration_ms: int,
    output: str | None = None,
    error: str | None = None,
    evidence_path: str | None = None,
    triggered_by: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Create a test run record.

    Args:
        project_id: Project ID
        test_db_id: Database ID of the test
        run_type: Type of run ('manual', 'ci', 'build', 'scheduled')
        result: Test result ('passed', 'failed', 'error', 'timeout', 'skipped')
        duration_ms: Execution duration in milliseconds
        output: Test output (may be truncated)
        error: Error message if failed
        evidence_path: Path to evidence (screenshots, logs)
        triggered_by: Who/what triggered the run
        session_id: Agent session ID if part of a build

    Returns:
        The created test run dict.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO test_runs (project_id, test_id, run_type, result, duration_ms,
                                  output, error, evidence_path, triggered_by, session_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, test_id, run_type, result, duration_ms,
                      output, error, evidence_path, triggered_by, session_id, created_at
            """,
            (
                project_id,
                test_db_id,
                run_type,
                result,
                duration_ms,
                output,
                error,
                evidence_path,
                triggered_by,
                session_id,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row)


def get_test_run(run_id: int) -> dict[str, Any] | None:
    """Get a test run by ID.

    Returns:
        Test run dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, test_id, run_type, result, duration_ms,
                   output, error, evidence_path, triggered_by, session_id, created_at
            FROM test_runs
            WHERE id = %s
            """,
            (run_id,),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def get_test_runs(
    project_id: str,
    test_db_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get test runs for a project, optionally filtered by test.

    Args:
        project_id: Project ID
        test_db_id: Optional database ID of test to filter by
        limit: Maximum number of runs to return (default 100)

    Returns:
        List of test run dicts, ordered by created_at DESC.
    """
    with get_connection() as conn, conn.cursor() as cur:
        if test_db_id is not None:
            cur.execute(
                """
                SELECT id, project_id, test_id, run_type, result, duration_ms,
                       output, error, evidence_path, triggered_by, session_id, created_at
                FROM test_runs
                WHERE project_id = %s AND test_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (project_id, test_db_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, test_id, run_type, result, duration_ms,
                       output, error, evidence_path, triggered_by, session_id, created_at
                FROM test_runs
                WHERE project_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (project_id, limit),
            )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_test_runs_by_session(
    project_id: str,
    session_id: str,
) -> list[dict[str, Any]]:
    """Get all test runs for a specific session.

    Args:
        project_id: Project ID
        session_id: Session ID

    Returns:
        List of test run dicts for the session.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, test_id, run_type, result, duration_ms,
                   output, error, evidence_path, triggered_by, session_id, created_at
            FROM test_runs
            WHERE project_id = %s AND session_id = %s
            ORDER BY created_at ASC
            """,
            (project_id, session_id),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_test_stats(
    project_id: str,
    test_db_id: int,
) -> dict[str, Any]:
    """Get aggregate statistics for a test.

    Args:
        project_id: Project ID
        test_db_id: Database ID of the test

    Returns:
        Dict with total_runs, passed, failed, error, timeout, skipped,
        avg_duration_ms, pass_rate, last_run_at.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) as total_runs,
                COUNT(*) FILTER (WHERE result = 'passed') as passed,
                COUNT(*) FILTER (WHERE result = 'failed') as failed,
                COUNT(*) FILTER (WHERE result = 'error') as error,
                COUNT(*) FILTER (WHERE result = 'timeout') as timeout,
                COUNT(*) FILTER (WHERE result = 'skipped') as skipped,
                AVG(duration_ms)::INTEGER as avg_duration_ms,
                MAX(created_at) as last_run_at
            FROM test_runs
            WHERE project_id = %s AND test_id = %s
            """,
            (project_id, test_db_id),
        )
        row = cur.fetchone()

    if not row:
        return {
            "total_runs": 0,
            "passed": 0,
            "failed": 0,
            "error": 0,
            "timeout": 0,
            "skipped": 0,
            "avg_duration_ms": None,
            "pass_rate": 0.0,
            "last_run_at": None,
        }

    total = row[0] or 0
    passed = row[1] or 0
    pass_rate = (passed / total * 100) if total > 0 else 0.0

    return {
        "total_runs": total,
        "passed": passed,
        "failed": row[2] or 0,
        "error": row[3] or 0,
        "timeout": row[4] or 0,
        "skipped": row[5] or 0,
        "avg_duration_ms": row[6],
        "pass_rate": round(pass_rate, 1),
        "last_run_at": row[7].isoformat() if row[7] else None,
    }


def get_recent_failures(
    project_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Get recent failed test runs with test info.

    Args:
        project_id: Project ID
        limit: Maximum number of failures to return

    Returns:
        List of test run dicts with test name/type added.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT tr.id, tr.project_id, tr.test_id, tr.run_type, tr.result, tr.duration_ms,
                   tr.output, tr.error, tr.evidence_path, tr.triggered_by, tr.session_id,
                   tr.created_at, t.test_id as test_id_str, t.name as test_name, t.test_type
            FROM test_runs tr
            INNER JOIN tests t ON tr.test_id = t.id
            WHERE tr.project_id = %s AND tr.result IN ('failed', 'error', 'timeout')
            ORDER BY tr.created_at DESC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

    result = []
    for row in rows:
        run_dict = _row_to_dict(row[:12])
        run_dict["test_id_str"] = row[12]
        run_dict["test_name"] = row[13]
        run_dict["test_type"] = row[14]
        result.append(run_dict)
    return result


def _row_to_dict(row: tuple | None) -> dict[str, Any]:
    """Convert a database row to a dict."""
    if row is None:
        return {}

    return {
        "id": row[0],
        "project_id": row[1],
        "test_id": row[2],
        "run_type": row[3],
        "result": row[4],
        "duration_ms": row[5],
        "output": row[6],
        "error": row[7],
        "evidence_path": row[8],
        "triggered_by": row[9],
        "session_id": row[10],
        "created_at": row[11].isoformat() if row[11] else None,
    }
