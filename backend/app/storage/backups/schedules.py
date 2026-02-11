"""Backup schedule operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..connection import get_connection
from .models import BACKUP_SCHEDULE_COLUMNS, row_to_schedule


def get_schedule(project_id: str) -> dict[str, Any] | None:
    """Get backup schedule for a project.

    Args:
        project_id: Project ID

    Returns:
        Schedule record or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {BACKUP_SCHEDULE_COLUMNS} FROM backup_schedules WHERE project_id = %s",
            (project_id,),
        )
        row = cur.fetchone()

    return row_to_schedule(row) if row else None


def upsert_schedule(
    project_id: str,
    enabled: bool,
    frequency: str,
    retention_days: int = 14,
) -> dict[str, Any]:
    """Create or update backup schedule for a project.

    Args:
        project_id: Project ID
        enabled: Whether schedule is active
        frequency: 'daily', 'weekly', or 'monthly'
        retention_days: Number of days to retain backups

    Returns:
        Schedule record

    Raises:
        RuntimeError: If upsert fails
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO backup_schedules (project_id, enabled, frequency, retention_days)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (project_id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                frequency = EXCLUDED.frequency,
                retention_days = EXCLUDED.retention_days,
                updated_at = NOW()
            RETURNING {BACKUP_SCHEDULE_COLUMNS}
            """,
            (project_id, enabled, frequency, retention_days),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise RuntimeError("Failed to upsert schedule")
    return row_to_schedule(row)


def update_schedule_last_run(project_id: str, next_run_at: datetime | None = None) -> bool:
    """Update schedule after a run.

    Args:
        project_id: Project ID
        next_run_at: Next scheduled run time

    Returns:
        True if updated, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE backup_schedules
            SET last_run_at = NOW(), next_run_at = %s, updated_at = NOW()
            WHERE project_id = %s
            RETURNING id
            """,
            (next_run_at, project_id),
        )
        row = cur.fetchone()
        conn.commit()

    return row is not None


def list_due_schedules() -> list[dict[str, Any]]:
    """Get all schedules that are due to run.

    Returns:
        List of schedule records where next_run_at <= NOW() and enabled = true
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {BACKUP_SCHEDULE_COLUMNS} FROM backup_schedules
            WHERE enabled = TRUE AND (next_run_at IS NULL OR next_run_at <= NOW())
            ORDER BY next_run_at ASC NULLS FIRST
            """
        )
        rows = cur.fetchall()

    return [row_to_schedule(row) for row in rows]
