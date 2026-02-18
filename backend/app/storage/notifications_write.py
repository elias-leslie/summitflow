"""Notifications write layer - status updates and deletion for notifications."""

from __future__ import annotations

from typing import Any

from .connection import get_connection
from .notifications_helpers import _row_to_dict

_RETURNING_COLS = (
    "RETURNING id, project_id, task_id, user_email, type, title, message, severity, status,"
    " metadata, created_at, read_at, dismissed_at"
)


def mark_as_read(notification_id: str) -> dict[str, Any] | None:
    """Mark a notification as read.

    Returns:
        Updated notification dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE notifications SET status = 'read', read_at = NOW() WHERE id = %s {_RETURNING_COLS}",
            (notification_id,),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def dismiss_notification(notification_id: str) -> dict[str, Any] | None:
    """Dismiss a notification.

    Returns:
        Updated notification dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE notifications SET status = 'dismissed', dismissed_at = NOW() WHERE id = %s {_RETURNING_COLS}",
            (notification_id,),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def dismiss_all_for_project(project_id: str) -> int:
    """Dismiss all notifications for a project.

    Returns:
        Number of notifications dismissed
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE notifications SET status = 'dismissed', dismissed_at = NOW()"
            " WHERE project_id = %s AND status != 'dismissed'",
            (project_id,),
        )
        count = cur.rowcount
        conn.commit()

    return count


def delete_notification(notification_id: str) -> bool:
    """Delete a notification.

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM notifications WHERE id = %s RETURNING id",
            (notification_id,),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None
