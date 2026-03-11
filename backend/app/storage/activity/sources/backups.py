"""Backup Events Source - Fetch activity events from backups table."""

from __future__ import annotations

from typing import Any, cast

from ...connection import get_connection
from ..types import ActivityEvent, BackupMetadata


def _row_to_event(row: tuple[Any, ...]) -> ActivityEvent:
    """Convert a backup database row to an ActivityEvent."""
    backup_id, proj_id, backup_type, status, size_bytes, completed_at, created_at = row
    event_time = completed_at or created_at
    size_mb = f" ({size_bytes / 1024 / 1024:.1f} MB)" if size_bytes else ""

    metadata: BackupMetadata = {
        "backup_id": backup_id,
        "backup_type": backup_type,
        "status": status,
        "size_bytes": size_bytes or 0,
    }

    return {
        "type": "backup",
        "message": f"{backup_type.title()} backup {status}{size_mb}",
        "timestamp": event_time.isoformat() if event_time else None,
        "project_id": proj_id,
        "metadata": cast(dict[str, Any], metadata),
    }


def _fetch_backup_rows(
    where_clause: str,
    params: list[str | int],
    limit: int,
) -> list[tuple[Any, ...]]:
    """Execute the backup query and return raw rows."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, project_id, backup_type, status, size_bytes, completed_at, created_at
            FROM backups
            {where_clause}
            ORDER BY COALESCE(completed_at, created_at) DESC
            LIMIT %s
            """,
            [*params, limit],
        )
        return cur.fetchall()


def get_recent_backup_events(
    project_id: str | None = None,
    limit: int = 20,
) -> list[ActivityEvent]:
    """Get recent backup events.

    Args:
        project_id: Filter by project (None for all)
        limit: Max events to return

    Returns:
        List of activity events for backups
    """
    where_clause = "WHERE status IN ('completed', 'failed')"
    params: list[str | int] = []

    if project_id:
        where_clause += " AND project_id = %s"
        params.append(project_id)

    rows = _fetch_backup_rows(where_clause, params, limit)
    return [_row_to_event(row) for row in rows]
