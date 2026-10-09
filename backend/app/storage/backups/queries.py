"""Aggregation and query operations for backups."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg

from .._sql import static_sql
from ..connection import get_connection, get_cursor
from .models import BACKUP_COLUMNS, row_to_backup


def fail_stale_running_backups(
    max_age_minutes: int = 30,
    error_message: str | None = None,
    *,
    is_source_active: Callable[[str], bool],
) -> int:
    """Fail old orphaned rows, never a backup with an active worker lease.

    Args:
        max_age_minutes: Minimum row age before checking for orphaned ownership
        error_message: Optional override for the failure reason stored on the row
        is_source_active: Existing source-lease lookup; lookup errors abort cleanup

    Returns:
        Number of running rows that were failed
    """
    resolved_error = error_message or (
        f"Backup has no active backup lease and its running record is older than {max_age_minutes} minutes"
    )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, COALESCE(source_id, project_id), COALESCE(verification_json #>> '{activity,run_id}', '')
            FROM backups
            WHERE (status = 'running'
              AND COALESCE(started_at, created_at) < NOW() - INTERVAL '1 minute' * %s)
              OR verification_json #>> '{activity,active}' = 'true'
            """,
            (max_age_minutes,),
        )
        candidates = cur.fetchall()
        # Resolve every lease before mutation. A Redis outage is unknown, not
        # evidence of a stopped worker. Cache sources to avoid repeated lookups.
        active = {str(source_id): is_source_active(str(source_id)) for source_id in {row[1] for row in candidates}}
        orphan_ids = [row[0] for row in candidates if not active[str(row[1])]]
        orphan_runs = [row[2] for row in candidates if not active[str(row[1])]]
        if not orphan_ids:
            return 0
        cur.execute(
            """
            UPDATE backups
            SET status = CASE WHEN status = 'running' THEN 'failed' ELSE status END,
                error_message = CASE WHEN status = 'running' THEN COALESCE(error_message, %s) ELSE error_message END,
                completed_at = CASE WHEN status = 'running' THEN NOW() ELSE completed_at END,
                verification_json = CASE WHEN verification_json #>> '{activity,active}' = 'true' THEN
                    jsonb_set(verification_json, '{activity}', verification_json -> 'activity' ||
                      '{"active":false,"phase":"failed","attention":true,"remote_outcome_unknown":true}'::jsonb)
                    ELSE verification_json END
            WHERE (id, COALESCE(verification_json #>> '{activity,run_id}', '')) IN
                (SELECT * FROM unnest(%s::text[], %s::text[]))
            RETURNING status
            """,
            (resolved_error, orphan_ids, orphan_runs),
        )
        failed_rows = cur.fetchall()
        conn.commit()

    return sum(row[0] == "failed" for row in failed_rows)


def cleanup_stale_backup_records(max_age_days: int = 30) -> int:
    """Delete failed records; running rows first need the lease-aware orphan check.

    Args:
        max_age_days: Delete stale records older than this many days

    Returns:
        Number of records deleted
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM backups
            WHERE status = 'failed'
              AND location IS NULL
              AND COALESCE(verification_json #>> '{offsite,status}', '') NOT IN ('pending', 'failed')
              AND created_at < NOW() - INTERVAL '%s days'
            RETURNING id
            """,
            (max_age_days,),
        )
        deleted = cur.fetchall()
        conn.commit()

    return len(deleted)


def cleanup_expired_backup_records(default_retention_days: int = 14, min_keep: int = 3) -> int:
    """Unlink bounded expired archives before deleting their catalogue evidence.

    Uses per-source retention_days from backup_sources table, falling back to
    default_retention_days for backups without a matching source.

    Pending uploads and active/pending/failed offsite copies are preserved and
    do not displace the minimum completed recovery records retained per source.
    Restic snapshot records belong to repository retention and reconciliation.

    Args:
        default_retention_days: Fallback for backups without a source retention setting
        min_keep: Minimum number of completed records to keep per source

    Returns:
        Number of records deleted
    """
    from ...tasks.backup_local_cleanup import _configured_local_roots
    from .sources import list_sources

    roots = _configured_local_roots()
    roots.extend(Path(source["path"]) / "backups" for source in list_sources() if source.get("path"))
    bounded_roots = [root.resolve() for root in roots if root.is_absolute() and root.resolve() != Path(root.anchor) and not any(part.is_symlink() for part in (root, *root.parents))]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, location FROM backups
            WHERE status = 'completed'
              AND (verification_json ->> 'format') IS DISTINCT FROM 'restic-v1'
              AND (verification_json #>> '{activity,active}') IS DISTINCT FROM 'true'
              AND (verification_json ->> 'pinned') IS DISTINCT FROM 'true'
              AND COALESCE(verification_json #>> '{offsite,status}', '') NOT IN ('pending', 'failed')
              AND created_at < NOW() - INTERVAL '1 day' * COALESCE(
                (SELECT bs.retention_days FROM backup_sources bs
                 WHERE bs.id = backups.source_id),
                %s
              )
              AND id NOT IN (
                SELECT id FROM (
                  SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY COALESCE(source_id, project_id) ORDER BY created_at DESC, id DESC
                  ) AS rn
                  FROM backups WHERE status = 'completed'
                    AND (verification_json ->> 'format') IS DISTINCT FROM 'restic-v1'
                    AND (verification_json #>> '{activity,active}') IS DISTINCT FROM 'true'
                    AND COALESCE(verification_json #>> '{offsite,status}', '') NOT IN ('pending', 'failed')
                ) ranked WHERE rn <= %s
              )
            FOR UPDATE
            """,
            (default_retention_days, min_keep),
        )
        candidates = cur.fetchall()
        deleted = 0
        for backup_id, location in candidates:
            if location:
                archive = Path(location)
                # Remote archives need backend-owned deletion evidence. Never
                # erase their only catalogue reference merely because they aged.
                if not archive.is_absolute() or str(location).startswith("//") or not archive.name.endswith((".tar.gz", ".tar.gz.age")):
                    continue
                if any(part.is_symlink() for part in (archive, *archive.parents)) or not any(archive.resolve().is_relative_to(root) for root in bounded_roots):
                    continue
                try:
                    archive.unlink(missing_ok=True)
                except OSError:
                    continue  # Failed unlink retains every recovery/evidence field.
                if archive.exists() or archive.is_symlink():
                    continue  # Replacement bytes appeared; retain the evidence.
            cur.execute("DELETE FROM backups WHERE id = %s RETURNING id", (backup_id,))
            deleted += int(cur.fetchone() is not None)
        conn.commit()

    return deleted


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
                    COUNT(*) FILTER (WHERE status = 'failed') as failed_count,
                    COALESCE(SUM(size_bytes) FILTER (WHERE verification_json->>'format' = 'restic-v1'), 0) as repository_logical_bytes,
                    COUNT(*) FILTER (WHERE verification_json->>'format' = 'restic-v1') as repository_point_count
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
        "measurement": "mixed-catalogue-logical-not-physical" if len(row) > 8 and row[8] else "catalogue-artifact-bytes",
        "archive_bytes": int(row[1] or 0) - int(row[7] or 0) if len(row) > 7 else int(row[1] or 0),
        "repository_logical_bytes": int(row[7] or 0) if len(row) > 7 else 0,
        "repository_point_count": int(row[8] or 0) if len(row) > 8 else 0,
        "repository_physical_bytes": None,
    }


def get_latest_backup(
    project_id: str | None = None,
    source_id: str | None = None,
    verification_key: str | None = None,
    *, connection: psycopg.Connection | None = None,
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

    with (connection.cursor() if connection else get_cursor()) as cur:
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
                bs.last_drill_backup_id,
                (
                    SELECT b.verification_json
                    FROM backups b
                    WHERE b.source_id = bs.id
                      AND b.status IN ('completed', 'completed_pending_upload')
                    ORDER BY b.completed_at DESC
                    LIMIT 1
                ) AS latest_verification_json,
                (
                    SELECT b.id
                    FROM backups b
                    WHERE b.source_id = bs.id
                      AND b.status IN ('completed', 'completed_pending_upload')
                    ORDER BY b.completed_at DESC
                    LIMIT 1
                ) AS latest_backup_id,
                (
                    SELECT b.verification_json -> 'activity'
                    FROM backups b
                    WHERE b.source_id = bs.id AND b.verification_json ? 'activity'
                    ORDER BY (b.verification_json #>> '{activity,active}' = 'true') DESC, b.created_at DESC
                    LIMIT 1
                ) AS backup_activity
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
            "latest_verification_json": row[14],
            "latest_backup_id": str(row[15]) if row[15] else None,
            "backup_activity": row[16],
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


def get_pending_native_offsite_backups() -> list[dict[str, Any]]:
    """Return retained native recovery points whose independent copy needs retry.

    Local completion remains truthful while a replica is unavailable. Restic
    snapshots use their repository reconciliation rather than native archive
    or SMB upload drain. Callers check current route and source leases before
    retry; disabled destinations must not erase previously recorded failures.
    """
    with get_cursor() as cur:
        cur.execute(
            static_sql(
                f"SELECT {BACKUP_COLUMNS} FROM backups "
                "WHERE status = 'completed' "
                "AND (verification_json ->> 'format') IS DISTINCT FROM 'restic-v1' "
                "AND verification_json #>> '{offsite,status}' IN ('pending', 'failed') "
                "ORDER BY created_at ASC, id ASC"
            ),
        )
        rows = cur.fetchall()
    return [row_to_backup(row) for row in rows]
