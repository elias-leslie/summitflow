"""Storage module for quality check results.

Tracks results from dt quality gate checks (pytest, ruff, mypy, biome, tsc)
and their fix status.
"""

import logging
from typing import Any, Literal

import psycopg

logger = logging.getLogger(__name__)

# Type definitions
CheckType = Literal["pytest", "ruff", "mypy", "biome", "tsc"]
Status = Literal["pass", "fail", "error", "skipped"]
TriggerType = Literal["commit", "manual", "ci", "agent"]


def create_check_result(
    conn: psycopg.Connection,
    project_id: str,
    check_type: CheckType,
    status: Status,
    *,
    check_name: str | None = None,
    error_count: int = 0,
    warning_count: int = 0,
    error_message: str | None = None,
    file_path: str | None = None,
    line_number: int | None = None,
    column_number: int | None = None,
    run_duration_ms: int | None = None,
    git_sha: str | None = None,
    triggered_by: TriggerType | None = None,
) -> dict[str, Any]:
    """Create a new quality check result.

    Args:
        conn: Database connection
        project_id: Project ID
        check_type: Type of check (pytest, ruff, mypy, biome, tsc)
        status: Result status (pass, fail, error, skipped)
        check_name: Specific test name or rule (optional)
        error_count: Number of errors
        warning_count: Number of warnings
        error_message: Error details
        file_path: File where error occurred
        line_number: Line number of error
        column_number: Column number of error
        run_duration_ms: Execution duration in milliseconds
        git_sha: Git commit SHA
        triggered_by: What triggered this check

    Returns:
        Created check result dict
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO quality_check_results
                (project_id, check_type, check_name, status, error_count, warning_count,
                 error_message, file_path, line_number, column_number,
                 run_duration_ms, git_sha, triggered_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, check_type, check_name, status, error_count,
                      warning_count, error_message, file_path, line_number, column_number,
                      run_duration_ms, git_sha, triggered_by, fix_attempted, fix_attempts,
                      fixed_at, fixed_by, created_at, updated_at
            """,
            (
                project_id,
                check_type,
                check_name,
                status,
                error_count,
                warning_count,
                error_message,
                file_path,
                line_number,
                column_number,
                run_duration_ms,
                git_sha,
                triggered_by,
            ),
        )
        row = cur.fetchone()
        if row is None:
            msg = "Failed to create check result"
            raise RuntimeError(msg)

        return _row_to_dict(row)


def get_check_result(conn: psycopg.Connection, result_id: int) -> dict[str, Any] | None:
    """Get a check result by ID."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, check_type, check_name, status, error_count,
                   warning_count, error_message, file_path, line_number, column_number,
                   run_duration_ms, git_sha, triggered_by, fix_attempted, fix_attempts,
                   fixed_at, fixed_by, created_at, updated_at
            FROM quality_check_results
            WHERE id = %s
            """,
            (result_id,),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def list_check_results(
    conn: psycopg.Connection,
    project_id: str,
    *,
    check_type: CheckType | None = None,
    status: Status | None = None,
    unfixed_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List check results for a project with optional filters.

    Args:
        conn: Database connection
        project_id: Project ID
        check_type: Filter by check type
        status: Filter by status
        unfixed_only: Only return unfixed failures
        limit: Max results to return
        offset: Pagination offset

    Returns:
        List of check result dicts
    """
    conditions = ["project_id = %s"]
    params: list[Any] = [project_id]

    if check_type:
        conditions.append("check_type = %s")
        params.append(check_type)

    if status:
        conditions.append("status = %s")
        params.append(status)

    if unfixed_only:
        conditions.append("status = 'fail'")
        conditions.append("fixed_at IS NULL")

    where_clause = " AND ".join(conditions)
    params.extend([limit, offset])

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, project_id, check_type, check_name, status, error_count,
                   warning_count, error_message, file_path, line_number, column_number,
                   run_duration_ms, git_sha, triggered_by, fix_attempted, fix_attempts,
                   fixed_at, fixed_by, created_at, updated_at
            FROM quality_check_results
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        return [_row_to_dict(row) for row in cur.fetchall()]


def get_unfixed_count(
    conn: psycopg.Connection,
    project_id: str,
    check_type: CheckType | None = None,
) -> int:
    """Count unfixed failures for a project.

    Args:
        conn: Database connection
        project_id: Project ID
        check_type: Optional filter by check type

    Returns:
        Count of unfixed failures
    """
    params: list[Any] = [project_id]
    type_filter = ""

    if check_type:
        type_filter = " AND check_type = %s"
        params.append(check_type)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM quality_check_results
            WHERE project_id = %s AND status = 'fail' AND fixed_at IS NULL{type_filter}
            """,
            params,
        )
        row = cur.fetchone()
        return row[0] if row else 0


def record_fix_attempt(
    conn: psycopg.Connection,
    result_id: int,
) -> dict[str, Any] | None:
    """Record a fix attempt for a check result.

    Increments attempt count and updates last attempt timestamp.

    Args:
        conn: Database connection
        result_id: Check result ID

    Returns:
        Updated check result dict
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE quality_check_results
            SET fix_attempted = TRUE,
                fix_attempts = fix_attempts + 1,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, project_id, check_type, check_name, status, error_count,
                      warning_count, error_message, file_path, line_number, column_number,
                      run_duration_ms, git_sha, triggered_by, fix_attempted, fix_attempts,
                      fixed_at, fixed_by, created_at, updated_at
            """,
            (result_id,),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def mark_fixed(
    conn: psycopg.Connection,
    result_id: int,
    fixed_by: str,
) -> dict[str, Any] | None:
    """Mark a check result as fixed.

    Args:
        conn: Database connection
        result_id: Check result ID
        fixed_by: Who/what fixed it (agent name or 'user')

    Returns:
        Updated check result dict
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE quality_check_results
            SET fixed_at = NOW(),
                fixed_by = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, project_id, check_type, check_name, status, error_count,
                      warning_count, error_message, file_path, line_number, column_number,
                      run_duration_ms, git_sha, triggered_by, fix_attempted, fix_attempts,
                      fixed_at, fixed_by, created_at, updated_at
            """,
            (fixed_by, result_id),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def get_project_health_summary(
    conn: psycopg.Connection,
    project_id: str,
) -> dict[str, Any]:
    """Get a summary of quality gate health for a project.

    Returns counts by check type and overall pass/fail status.

    Args:
        conn: Database connection
        project_id: Project ID

    Returns:
        Health summary dict with counts per check type
    """
    with conn.cursor() as cur:
        # Get latest result per check type
        cur.execute(
            """
            WITH latest_results AS (
                SELECT DISTINCT ON (check_type)
                    check_type, status, error_count, warning_count, created_at
                FROM quality_check_results
                WHERE project_id = %s
                ORDER BY check_type, created_at DESC
            )
            SELECT check_type, status, error_count, warning_count
            FROM latest_results
            """,
            (project_id,),
        )
        results = cur.fetchall()

        # Get unfixed counts
        cur.execute(
            """
            SELECT check_type, COUNT(*)
            FROM quality_check_results
            WHERE project_id = %s AND status = 'fail' AND fixed_at IS NULL
            GROUP BY check_type
            """,
            (project_id,),
        )
        unfixed: dict[str, int] = dict(cur.fetchall())

        summary: dict[str, Any] = {
            "project_id": project_id,
            "checks": {},
            "overall_pass": True,
            "total_unfixed": sum(unfixed.values()),
        }

        for check_type, status, error_count, warning_count in results:
            summary["checks"][check_type] = {
                "status": status,
                "error_count": error_count,
                "warning_count": warning_count,
                "unfixed_count": unfixed.get(check_type, 0),
            }
            if status != "pass":
                summary["overall_pass"] = False

        return summary


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a database row to a dict."""
    return {
        "id": row[0],
        "project_id": row[1],
        "check_type": row[2],
        "check_name": row[3],
        "status": row[4],
        "error_count": row[5],
        "warning_count": row[6],
        "error_message": row[7],
        "file_path": row[8],
        "line_number": row[9],
        "column_number": row[10],
        "run_duration_ms": row[11],
        "git_sha": row[12],
        "triggered_by": row[13],
        "fix_attempted": row[14],
        "fix_attempts": row[15],
        "fixed_at": row[16],
        "fixed_by": row[17],
        "created_at": row[18],
        "updated_at": row[19],
    }
