"""Persistence helpers for maintenance workflow observability."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

from .connection import get_connection

_SELECT_COLS = """
    id, workflow_name, status, started_at, finished_at, duration_ms,
    rows_cleaned, summary, error_message, created_at
"""


def _table_exists(cur: Any) -> bool:
    """Return True when the maintenance_runs table exists."""
    cur.execute("SELECT to_regclass('public.maintenance_runs')")
    row = cur.fetchone()
    return bool(row and row[0])


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": int(row[0]),
        "workflow_name": str(row[1]),
        "status": str(row[2]),
        "started_at": row[3],
        "finished_at": row[4],
        "duration_ms": int(row[5]) if row[5] is not None else None,
        "rows_cleaned": int(row[6] or 0),
        "summary": row[7] or {},
        "error_message": row[8],
        "created_at": row[9],
    }


def record_maintenance_run(
    workflow_name: str,
    status: str,
    *,
    started_at: datetime,
    finished_at: datetime | None = None,
    rows_cleaned: int = 0,
    summary: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> dict[str, Any] | None:
    """Persist one maintenance workflow run for operator visibility."""
    if summary is None:
        summary = {}
    if finished_at is None:
        finished_at = datetime.now(UTC)

    duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))

    with get_connection() as conn, conn.cursor() as cur:
        if not _table_exists(cur):
            return None
        cur.execute(
            f"""
            INSERT INTO maintenance_runs (
                workflow_name, status, started_at, finished_at, duration_ms,
                rows_cleaned, summary, error_message
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_SELECT_COLS}
            """,
            (
                workflow_name,
                status,
                started_at,
                finished_at,
                duration_ms,
                rows_cleaned,
                Jsonb(summary),
                error_message,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def list_maintenance_runs(
    *,
    limit: int = 20,
    workflow_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent maintenance runs ordered by newest start time first."""
    with get_connection() as conn, conn.cursor() as cur:
        if not _table_exists(cur):
            return []

        if workflow_name is None:
            cur.execute(
                f"""
                SELECT {_SELECT_COLS}
                FROM maintenance_runs
                ORDER BY started_at DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
        else:
            cur.execute(
                f"""
                SELECT {_SELECT_COLS}
                FROM maintenance_runs
                WHERE workflow_name = %s
                ORDER BY started_at DESC, id DESC
                LIMIT %s
                """,
                (workflow_name, limit),
            )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_latest_maintenance_runs(
    workflow_names: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return the latest run per workflow name."""
    with get_connection() as conn, conn.cursor() as cur:
        if not _table_exists(cur):
            return {}

        if workflow_names:
            cur.execute(
                f"""
                SELECT DISTINCT ON (workflow_name) {_SELECT_COLS}
                FROM maintenance_runs
                WHERE workflow_name = ANY(%s::text[])
                ORDER BY workflow_name, started_at DESC, id DESC
                """,
                (list(workflow_names),),
            )
        else:
            cur.execute(
                f"""
                SELECT DISTINCT ON (workflow_name) {_SELECT_COLS}
                FROM maintenance_runs
                ORDER BY workflow_name, started_at DESC, id DESC
                """
            )
        rows = cur.fetchall()

    return {str(row[1]): _row_to_dict(row) for row in rows}
