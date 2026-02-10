"""Aggregation and query operations for backups."""

from __future__ import annotations

from typing import Any

from ..connection import get_connection
from .models import BACKUP_COLUMNS, row_to_backup


def cleanup_stale_backup_records(max_age_days: int = 30) -> int:
    """Delete failed/running backup records older than max_age_days.

    Args:
        max_age_days: Delete stale records older than this many days

    Returns:
        Number of records deleted
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM backups
            WHERE status IN ('failed', 'running')
              AND created_at < NOW() - INTERVAL '%s days'
            RETURNING id
            """,
            (max_age_days,),
        )
        deleted = cur.fetchall()
        conn.commit()

    return len(deleted)


def get_storage_summary(project_id: str | None = None) -> dict[str, Any]:
    """Get storage usage summary.

    Args:
        project_id: Filter by project (None for all)

    Returns:
        Storage summary with total_bytes, backup_count, by_status
    """
    where_clause = "WHERE project_id = %s" if project_id else ""
    params = [project_id] if project_id else []

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                COUNT(*) as total_count,
                COALESCE(SUM(size_bytes), 0) as total_bytes,
                COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
                COUNT(*) FILTER (WHERE status = 'pending') as pending_count,
                COUNT(*) FILTER (WHERE status = 'running') as running_count,
                COUNT(*) FILTER (WHERE status = 'failed') as failed_count
            FROM backups
            {where_clause}
            """,
            params,
        )
        row = cur.fetchone()

    if not row:
        return {
            "total_count": 0,
            "total_bytes": 0,
            "by_status": {},
        }

    by_status: dict[str, int] = {}
    if row[2]:
        by_status["completed"] = int(row[2])
    if row[3]:
        by_status["pending"] = int(row[3])
    if row[4]:
        by_status["running"] = int(row[4])
    if row[5]:
        by_status["failed"] = int(row[5])

    return {
        "total_count": int(row[0]) if row[0] else 0,
        "total_bytes": int(row[1]) if row[1] else 0,
        "by_status": by_status,
    }


def get_latest_backup(project_id: str) -> dict[str, Any] | None:
    """Get the most recent completed backup for a project.

    Args:
        project_id: Project ID

    Returns:
        Latest completed backup record or None if no completed backups exist
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {BACKUP_COLUMNS} FROM backups "
            "WHERE project_id = %s AND status = 'completed' "
            "ORDER BY completed_at DESC LIMIT 1",
            (project_id,),
        )
        row = cur.fetchone()

    return row_to_backup(row) if row else None
