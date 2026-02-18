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


def get_notifications_by_user_email(
    user_email: str,
    status_filter: NotificationStatus | None = "pending",
    mark_as_seen: bool = True,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Get notifications for a specific user by email.

    This is used by game clients to fetch user-specific notifications
    (e.g., when their crowdsourced idea is implemented).

    Args:
        user_email: User's email address
        status_filter: Filter by status (default: pending only)
        mark_as_seen: Whether to mark returned notifications as read (default: True)
        limit: Max results (default 20)

    Returns:
        List of notification dicts
    """
    with get_connection() as conn, conn.cursor() as cur:
        if status_filter:
            cur.execute(
                _SELECT_COLS + "WHERE user_email = %s AND status = %s ORDER BY created_at DESC LIMIT %s",
                (user_email, status_filter, limit),
            )
        else:
            cur.execute(
                _SELECT_COLS + "WHERE user_email = %s ORDER BY created_at DESC LIMIT %s",
                (user_email, limit),
            )

        rows = cur.fetchall()
        notifications = [_row_to_dict(row) for row in rows]

        if mark_as_seen and notifications:
            notification_ids = [n["id"] for n in notifications if n["status"] == "pending"]
            if notification_ids:
                cur.execute(
                    "UPDATE notifications SET status = 'read', read_at = NOW() WHERE id = ANY(%s::text[])",
                    (notification_ids,),
                )
                conn.commit()

    return notifications
