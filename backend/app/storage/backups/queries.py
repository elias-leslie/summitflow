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


def cleanup_expired_backup_records(default_retention_days: int = 14, min_keep: int = 3) -> int:
    """Delete completed backup records older than their source's retention_days.

    Uses per-source retention_days from backup_sources table, falling back to
    default_retention_days for backups without a matching source.

    A window function ensures at least min_keep completed records
    are preserved per source regardless of age.

    Args:
        default_retention_days: Fallback for backups without a source retention setting
        min_keep: Minimum number of completed records to keep per source

    Returns:
        Number of records deleted
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM backups
            WHERE status = 'completed'
              AND created_at < NOW() - INTERVAL '1 day' * COALESCE(
                (SELECT bs.retention_days FROM backup_sources bs
                 WHERE bs.id = backups.source_id),
                %s
              )
              AND id NOT IN (
                SELECT id FROM (
                  SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY source_id ORDER BY created_at DESC
                  ) AS rn
                  FROM backups WHERE status = 'completed'
                ) ranked WHERE rn <= %s
              )
            RETURNING id
            """,
            (default_retention_days, min_keep),
        )
        deleted = cur.fetchall()
        conn.commit()

    return len(deleted)


def get_storage_summary(
    project_id: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Get storage usage summary.

    Args:
        project_id: Filter by project (None for all)
        source_id: Filter by source (takes precedence over project_id)

    Returns:
        Storage summary with total_bytes, backup_count, by_status
    """
    if source_id:
        where_clause = "WHERE source_id = %s"
        params = [source_id]
    elif project_id:
        where_clause = "WHERE project_id = %s"
        params = [project_id]
    else:
        where_clause = ""
        params = []

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


def get_latest_backup(
    project_id: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any] | None:
    """Get the most recent completed backup for a source or project.

    Args:
        project_id: Project ID (used if source_id not provided)
        source_id: Source ID (takes precedence)

    Returns:
        Latest completed backup record or None if no completed backups exist
    """
    if source_id:
        where = "source_id = %s"
        param = source_id
    elif project_id:
        where = "project_id = %s"
        param = project_id
    else:
        return None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {BACKUP_COLUMNS} FROM backups "
            f"WHERE {where} AND status = 'completed' "
            "ORDER BY completed_at DESC LIMIT 1",
            (param,),
        )
        row = cur.fetchone()

    return row_to_backup(row) if row else None
