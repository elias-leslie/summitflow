"""Storage module for quality check results.

Tracks results from st check quality gate checks (pytest, vitest, ruff, types, biome,
tsc) and their fix status.
"""

from __future__ import annotations

from typing import Any, Literal

import psycopg

from ._qcr_helpers import (
    RETURNING,
    SELECT_COLS,
    CheckResult,
    exec_returning,
    fetch_health_data,
    row_to_dict,
)
from ._sql import static_sql
from .connection import get_connection

CheckType = Literal["pytest", "vitest", "ruff", "types", "biome", "tsc"]
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
) -> CheckResult:
    """Create a new quality check result and return it."""
    result = exec_returning(
        conn,
        f"INSERT INTO quality_check_results"
        f" (project_id, check_type, check_name, status, error_count, warning_count,"
        f"  error_message, file_path, line_number, column_number,"
        f"  run_duration_ms, git_sha, triggered_by)"
        f" VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) {RETURNING}",
        (
            project_id, check_type, check_name, status,
            error_count, warning_count, error_message,
            file_path, line_number, column_number,
            run_duration_ms, git_sha, triggered_by,
        ),
    )
    if result is None:
        msg = "Failed to create check result"
        raise RuntimeError(msg)
    return result


def get_check_result(conn: psycopg.Connection, result_id: int) -> CheckResult | None:
    """Get a check result by ID."""
    with conn.cursor() as cur:
        cur.execute(
            static_sql(f"SELECT {SELECT_COLS} FROM quality_check_results WHERE id = %s"), (result_id,)
        )
        row = cur.fetchone()
        return row_to_dict(row) if row else None


def list_check_results(
    conn: psycopg.Connection,
    project_id: str,
    *,
    check_type: CheckType | None = None,
    status: Status | None = None,
    unfixed_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[CheckResult]:
    """List check results for a project with optional filters."""
    conditions: list[str] = ["project_id = %s"]
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
    params.extend([limit, offset])
    where_clause = " AND ".join(conditions)
    with conn.cursor() as cur:
        cur.execute(
            static_sql(
                f"SELECT {SELECT_COLS} FROM quality_check_results"
                f" WHERE {where_clause} ORDER BY created_at DESC LIMIT %s OFFSET %s"
            ),
            params,
        )
        return [row_to_dict(row) for row in cur.fetchall()]


def get_unfixed_count(
    conn: psycopg.Connection, project_id: str, check_type: CheckType | None = None
) -> int:
    """Count unfixed failures for a project."""
    params: list[Any] = [project_id]
    type_filter = ""
    if check_type:
        type_filter = " AND check_type = %s"
        params.append(check_type)
    with conn.cursor() as cur:
        cur.execute(
            static_sql(
                f"SELECT COUNT(*) FROM quality_check_results"
                f" WHERE project_id = %s AND status = 'fail' AND fixed_at IS NULL{type_filter}"
            ),
            params,
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


def record_fix_attempt(conn: psycopg.Connection, result_id: int) -> CheckResult | None:
    """Record a fix attempt — increments attempt count and updates timestamp."""
    return exec_returning(
        conn,
        f"UPDATE quality_check_results"
        f" SET fix_attempted = TRUE, fix_attempts = fix_attempts + 1, updated_at = NOW()"
        f" WHERE id = %s {RETURNING}",
        (result_id,),
    )


def mark_fixed(
    conn: psycopg.Connection, result_id: int, fixed_by: str
) -> CheckResult | None:
    """Mark a check result as fixed."""
    return exec_returning(
        conn,
        f"UPDATE quality_check_results"
        f" SET fixed_at = NOW(), fixed_by = %s, updated_at = NOW() WHERE id = %s {RETURNING}",
        (fixed_by, result_id),
    )


def get_project_health_summary(conn: psycopg.Connection, project_id: str) -> CheckResult:
    """Get a summary of quality gate health for a project."""
    with conn.cursor() as cur:
        results, unfixed = fetch_health_data(cur, project_id)
    checks: dict[str, Any] = {}
    overall_pass = True
    for check_type, status, error_count, warning_count in results:
        checks[str(check_type)] = {
            "status": status, "error_count": error_count,
            "warning_count": warning_count, "unfixed_count": unfixed.get(str(check_type), 0),
        }
        if status != "pass":
            overall_pass = False
    return {
        "project_id": project_id, "checks": checks,
        "overall_pass": overall_pass, "total_unfixed": sum(unfixed.values()),
    }


def auto_close_resolved(
    conn: psycopg.Connection, project_id: str, check_type: CheckType
) -> tuple[int, list[str]]:
    """Auto-close unfixed issues when a check passes."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT escalation_task_id FROM quality_check_results"
            " WHERE project_id = %s AND check_type = %s"
            " AND status = 'fail' AND fixed_at IS NULL AND escalation_task_id IS NOT NULL",
            (project_id, check_type),
        )
        task_ids = [str(row[0]) for row in cur.fetchall()]
        cur.execute(
            "UPDATE quality_check_results"
            " SET fixed_at = NOW(), fixed_by = 'auto_close_resolved', updated_at = NOW()"
            " WHERE project_id = %s AND check_type = %s AND status = 'fail' AND fixed_at IS NULL",
            (project_id, check_type),
        )
        return cur.rowcount, task_ids


def mark_escalated(
    conn: psycopg.Connection, result_id: int, task_id: str
) -> CheckResult | None:
    """Mark a check result as escalated to a blocking task."""
    return exec_returning(
        conn,
        f"UPDATE quality_check_results"
        f" SET escalation_task_id = %s, updated_at = NOW() WHERE id = %s {RETURNING}",
        (task_id, result_id),
    )


def cleanup_old_results(
    *,
    max_pass_age_days: int = 21,
    max_fixed_age_days: int = 45,
) -> dict[str, int]:
    """Delete old pass/fixed/skipped results while retaining active failures."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH deleted AS (
                DELETE FROM quality_check_results
                WHERE (
                    status IN ('pass', 'skipped')
                    AND created_at < NOW() - (%s * INTERVAL '1 day')
                ) OR (
                    fixed_at IS NOT NULL
                    AND fixed_at < NOW() - (%s * INTERVAL '1 day')
                )
                RETURNING status, fixed_at
            )
            SELECT
                COUNT(*) FILTER (WHERE status = 'pass' AND fixed_at IS NULL) AS pass_deleted,
                COUNT(*) FILTER (WHERE status = 'skipped' AND fixed_at IS NULL) AS skipped_deleted,
                COUNT(*) FILTER (WHERE fixed_at IS NOT NULL) AS fixed_deleted
            FROM deleted
            """,
            (max_pass_age_days, max_fixed_age_days),
        )
        row = cur.fetchone()
        conn.commit()

    return {
        "pass_deleted": int(row[0] or 0) if row else 0,
        "skipped_deleted": int(row[1] or 0) if row else 0,
        "fixed_deleted": int(row[2] or 0) if row else 0,
    }
