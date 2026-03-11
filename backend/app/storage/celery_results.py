"""Retention helpers for Celery result backend tables."""

from __future__ import annotations

from typing import Any

from psycopg import sql

from .connection import get_connection


def _table_exists(cur: Any, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    row = cur.fetchone()
    return bool(row and row[0])


def _cleanup_table(cur: Any, table_name: str, max_age_days: int) -> int:
    if not _table_exists(cur, table_name):
        return 0

    cur.execute(
        sql.SQL(
            """
            WITH deleted AS (
                DELETE FROM {table}
                WHERE date_done IS NOT NULL
                  AND date_done < NOW() - (%s * INTERVAL '1 day')
                RETURNING 1
            )
            SELECT COUNT(*) FROM deleted
            """
        ).format(table=sql.Identifier(table_name)),
        (max_age_days,),
    )
    row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def cleanup_old_celery_results(
    *,
    max_task_age_days: int = 30,
    max_group_age_days: int = 30,
) -> dict[str, int]:
    """Delete old Celery task and task-group metadata rows."""
    with get_connection() as conn, conn.cursor() as cur:
        taskmeta_deleted = _cleanup_table(cur, "celery_taskmeta", max_task_age_days)
        tasksetmeta_deleted = _cleanup_table(cur, "celery_tasksetmeta", max_group_age_days)
        conn.commit()

    return {
        "taskmeta_deleted": taskmeta_deleted,
        "tasksetmeta_deleted": tasksetmeta_deleted,
    }
