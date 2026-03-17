"""Notifications query helpers - read-only DB access for notifications."""

from __future__ import annotations

from typing import Any

from .connection import get_connection
from .notifications_helpers import NotificationStatus, _row_to_dict

_SELECT_COLS = """
    SELECT id, project_id, task_id, user_email, type, title, message, severity, status,
           metadata, created_at, read_at, dismissed_at
    FROM notifications
"""


def get_notification(notification_id: str) -> dict[str, Any] | None:
    """Get a notification by ID.

    Returns:
        Notification dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            _SELECT_COLS + "WHERE id = %s",
            (notification_id,),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def list_notifications(
    project_id: str,
    status_filter: NotificationStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    include_dismissed: bool = False,
) -> list[dict[str, Any]]:
    """List notifications for a project.

    Args:
        project_id: Project ID
        status_filter: Optional status filter (pending, read, dismissed)
        limit: Max results (default 50)
        offset: Result offset
        include_dismissed: Include dismissed notifications (default False)

    Returns:
        List of notification dicts
    """
    with get_connection() as conn, conn.cursor() as cur:
        if status_filter:
            cur.execute(
                _SELECT_COLS + "WHERE project_id = %s AND status = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (project_id, status_filter, limit, offset),
            )
        elif not include_dismissed:
            cur.execute(
                _SELECT_COLS + "WHERE project_id = %s AND status != 'dismissed' ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (project_id, limit, offset),
            )
        else:
            cur.execute(
                _SELECT_COLS + "WHERE project_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (project_id, limit, offset),
            )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_pending_count(project_id: str) -> int:
    """Get count of pending notifications for a project.

    Returns:
        Number of pending notifications
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM notifications WHERE project_id = %s AND status = 'pending'",
            (project_id,),
        )
        row = cur.fetchone()

    return row[0] if row else 0


def cleanup_old_notifications(
    *,
    max_read_age_days: int = 45,
    max_dismissed_age_days: int = 14,
    max_pending_age_days: int = 90,
) -> dict[str, int]:
    """Delete old notifications by status-specific retention windows."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH deleted AS (
                DELETE FROM notifications
                WHERE (
                    status = 'read'
                    AND read_at IS NOT NULL
                    AND read_at < NOW() - (%s * INTERVAL '1 day')
                ) OR (
                    status = 'dismissed'
                    AND dismissed_at IS NOT NULL
                    AND dismissed_at < NOW() - (%s * INTERVAL '1 day')
                ) OR (
                    status = 'pending'
                    AND created_at < NOW() - (%s * INTERVAL '1 day')
                )
                RETURNING status
            )
            SELECT
                COUNT(*) FILTER (WHERE status = 'read') AS read_deleted,
                COUNT(*) FILTER (WHERE status = 'dismissed') AS dismissed_deleted,
                COUNT(*) FILTER (WHERE status = 'pending') AS pending_deleted
            FROM deleted
            """,
            (max_read_age_days, max_dismissed_age_days, max_pending_age_days),
        )
        row = cur.fetchone()
        conn.commit()

    return {
        "read_deleted": int(row[0] or 0) if row else 0,
        "dismissed_deleted": int(row[1] or 0) if row else 0,
        "pending_deleted": int(row[2] or 0) if row else 0,
    }
