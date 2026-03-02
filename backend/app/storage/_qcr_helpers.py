"""Private helpers for quality_check_results storage module."""

from typing import Any

import psycopg

CheckResult = dict[str, Any]

_COLS = (
    "id, project_id, check_type, check_name, status, error_count, warning_count,"
    " error_message, file_path, line_number, column_number, run_duration_ms, git_sha,"
    " triggered_by, fix_attempted, fix_attempts, fixed_at, fixed_by, created_at,"
    " updated_at, escalation_task_id"
)
RETURNING = f"RETURNING {_COLS}"
SELECT_COLS = _COLS
_FIELDS = [f.strip() for f in _COLS.split(",")]


def row_to_dict(row: tuple[Any, ...]) -> CheckResult:
    """Convert a database row tuple to a dict."""
    return dict(zip(_FIELDS, row, strict=False))


def exec_returning(
    conn: psycopg.Connection, sql: str, params: tuple[Any, ...]
) -> CheckResult | None:
    """Execute a statement with RETURNING and return the first row as a dict."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row_to_dict(row) if row else None


def fetch_health_data(
    cur: psycopg.Cursor, project_id: str
) -> tuple[list[tuple[Any, ...]], dict[str, int]]:
    """Fetch latest-per-check-type rows and unfixed counts."""
    cur.execute(
        "WITH latest AS ("
        " SELECT DISTINCT ON (check_type) check_type, status, error_count, warning_count"
        " FROM quality_check_results WHERE project_id = %s ORDER BY check_type, created_at DESC"
        ") SELECT check_type, status, error_count, warning_count FROM latest",
        (project_id,),
    )
    results = cur.fetchall()
    cur.execute(
        "SELECT check_type, COUNT(*) FROM quality_check_results"
        " WHERE project_id = %s AND status = 'fail' AND fixed_at IS NULL GROUP BY check_type",
        (project_id,),
    )
    unfixed: dict[str, int] = {str(r[0]): int(r[1]) for r in cur.fetchall()}
    return results, unfixed
