"""Aggregation and query operations for backups."""

from __future__ import annotations

from typing import Any

from .._sql import static_sql
from ..connection import get_connection, get_cursor
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
            WHERE status IN ('completed', 'completed_pending_upload')
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
                  FROM backups WHERE status IN ('completed', 'completed_pending_upload')
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

    with get_cursor() as cur:
        cur.execute(
            static_sql(
                f"""
                SELECT
                    COUNT(*) as total_count,
                    COALESCE(SUM(size_bytes), 0) as total_bytes,
                    COUNT(*) FILTER (WHERE status IN ('completed', 'completed_pending_upload')) as completed_count,
                    COUNT(*) FILTER (WHERE status = 'completed_pending_upload') as pending_upload_count,
                    COUNT(*) FILTER (WHERE status = 'pending') as pending_count,
                    COUNT(*) FILTER (WHERE status = 'running') as running_count,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed_count
                FROM backups
                {where_clause}
                """
            ),
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
        by_status["completed_pending_upload"] = int(row[3])
    if row[4]:
        by_status["pending"] = int(row[4])
    if row[5]:
        by_status["running"] = int(row[5])
    if row[6]:
        by_status["failed"] = int(row[6])

    return {
        "total_count": int(row[0]) if row[0] else 0,
        "total_bytes": int(row[1]) if row[1] else 0,
        "by_status": by_status,
        "pending_upload_count": int(row[3]) if row[3] else 0,
    }


def get_latest_backup(
    project_id: str | None = None,
    source_id: str | None = None,
    verification_key: str | None = None,
) -> dict[str, Any] | None:
    """Get the most recent completed backup for a source or project.

    Args:
        project_id: Project ID (used if source_id not provided)
        source_id: Source ID (takes precedence)
        verification_key: Optional top-level verification_json key to require

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

    filters = [
        where,
        "status IN ('completed', 'completed_pending_upload')",
    ]
    params: list[Any] = [param]
    if verification_key:
        filters.append("verification_json ? %s")
        params.append(verification_key)

    with get_cursor() as cur:
        cur.execute(
            static_sql(
                f"SELECT {BACKUP_COLUMNS} FROM backups "
                f"WHERE {' AND '.join(filters)} "
                "ORDER BY completed_at DESC LIMIT 1"
            ),
            params,
        )
        row = cur.fetchone()

    return row_to_backup(row) if row else None


def get_backup_health_summary() -> list[dict[str, Any]]:
    """Get per-source backup health: last success, failure count (7d), next scheduled.

    Returns:
        List of dicts with source_id, source_name, source_type, last_success_at,
        failure_count_7d, next_run_at, enabled
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                bs.id,
                bs.name,
                bs.source_type,
                bs.enabled,
                bs.next_run_at,
                (
                    SELECT MAX(b.completed_at)
                    FROM backups b
                    WHERE b.source_id = bs.id
                      AND b.status IN ('completed', 'completed_pending_upload')
                ) AS last_success_at,
                (
                    SELECT COUNT(*)
                    FROM backups b
                    WHERE b.source_id = bs.id
                      AND b.status = 'failed'
                      AND b.created_at >= NOW() - INTERVAL '7 days'
                ) AS failure_count_7d,
                (
                    SELECT b.status
                    FROM backups b
                    WHERE b.source_id = bs.id
                    ORDER BY b.created_at DESC
                    LIMIT 1
                ) AS last_backup_status,
                (
                    SELECT COUNT(*)
                    FROM backups b
                    WHERE b.source_id = bs.id
                      AND b.status = 'completed_pending_upload'
                ) AS pending_upload_count,
                bs.last_restore_tested_at,
                bs.last_restore_test_ok,
                bs.last_drill_at,
                bs.last_drill_ok,
                bs.last_drill_backup_id
            FROM backup_sources bs
            ORDER BY bs.source_type, bs.name
            """
        )
        rows = cur.fetchall()

    return [
        {
            "source_id": row[0],
            "source_name": row[1],
            "source_type": row[2],
            "enabled": row[3],
            "next_run_at": row[4].isoformat() if row[4] else None,
            "last_success_at": row[5].isoformat() if row[5] else None,
            "failure_count_7d": int(row[6]) if row[6] else 0,
            "last_backup_status": row[7],
            "pending_upload_count": int(row[8]) if row[8] else 0,
            "last_restore_tested_at": row[9].isoformat() if row[9] else None,
            "last_restore_test_ok": row[10],
            "last_drill_at": row[11].isoformat() if row[11] else None,
            "last_drill_ok": row[12],
            "last_drill_backup_id": row[13],
        }
        for row in rows
    ]


def update_source_restore_test(
    source_id: str,
    ok: bool,
    error: str | None = None,
) -> None:
    """Record the result of a restore test for a backup source."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE backup_sources
            SET last_restore_tested_at = NOW(),
                last_restore_test_ok = %s,
                last_restore_test_error = %s
            WHERE id = %s
            """,
            (ok, error, source_id),
        )
        conn.commit()


def update_source_drill_result(
    source_id: str,
    ok: bool,
    backup_id: str | None = None,
    result: dict | None = None,
) -> None:
    """Record the result of a restore drill for a backup source."""
    import json

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE backup_sources
            SET last_drill_at = NOW(),
                last_drill_ok = %s,
                last_drill_backup_id = %s,
                last_drill_result = %s
            WHERE id = %s
            """,
            (ok, backup_id, json.dumps(result) if result else None, source_id),
        )
        conn.commit()


def promote_pending_upload(backup_id: str, location: str | None = None) -> bool:
    """Promote a completed_pending_upload backup to completed after successful upload."""
    with get_connection() as conn, conn.cursor() as cur:
        updates = ["status = 'completed'"]
        params: list[Any] = []
        if location:
            updates.append("location = %s")
            params.append(location)
        params.append(backup_id)
        cur.execute(
            static_sql(
                f"UPDATE backups SET {', '.join(updates)} "
                "WHERE id = %s AND status = 'completed_pending_upload' "
                "RETURNING id"
            ),
            params,
        )
        row = cur.fetchone()
        conn.commit()
    return row is not None


def get_pending_upload_backups() -> list[dict[str, Any]]:
    """Get all backups with completed_pending_upload status."""
    with get_cursor() as cur:
        cur.execute(
            static_sql(
                f"SELECT {BACKUP_COLUMNS} FROM backups "
                "WHERE status = 'completed_pending_upload' "
                "ORDER BY created_at ASC"
            ),
        )
        rows = cur.fetchall()
    return [row_to_backup(row) for row in rows]
