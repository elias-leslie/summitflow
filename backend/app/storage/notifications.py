"""Notifications storage layer - Notification CRUD and status management.

This module provides data access for notification alerts.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from .connection import get_connection

NotificationType = Literal["task_failed", "task_needs_input", "task_completed", "system"]
NotificationSeverity = Literal["info", "warning", "error", "critical"]
NotificationStatus = Literal["pending", "read", "dismissed"]


def _generate_notification_id() -> str:
    """Generate a unique notification ID."""
    return f"notif-{uuid.uuid4().hex[:8]}"


def create_notification(
    project_id: str,
    notification_type: NotificationType,
    title: str,
    message: str,
    severity: NotificationSeverity = "info",
    task_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new notification.

    Args:
        project_id: Project ID
        notification_type: Type of notification (task_failed, task_needs_input, etc)
        title: Short notification title
        message: Detailed notification message
        severity: Severity level (info, warning, error, critical)
        task_id: Optional task ID to link to
        metadata: Optional additional metadata

    Returns:
        Created notification dict
    """
    import json

    notification_id = _generate_notification_id()
    meta = metadata or {}

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notifications (id, project_id, task_id, type, title, message, severity, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id, project_id, task_id, type, title, message, severity, status,
                      metadata, created_at, read_at, dismissed_at
            """,
            (
                notification_id,
                project_id,
                task_id,
                notification_type,
                title,
                message,
                severity,
                json.dumps(meta),
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row)


def get_notification(notification_id: str) -> dict[str, Any] | None:
    """Get a notification by ID.

    Returns:
        Notification dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, task_id, type, title, message, severity, status,
                   metadata, created_at, read_at, dismissed_at
            FROM notifications
            WHERE id = %s
            """,
            (notification_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _row_to_dict(row)


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
                """
                SELECT id, project_id, task_id, type, title, message, severity, status,
                       metadata, created_at, read_at, dismissed_at
                FROM notifications
                WHERE project_id = %s AND status = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (project_id, status_filter, limit, offset),
            )
        elif not include_dismissed:
            cur.execute(
                """
                SELECT id, project_id, task_id, type, title, message, severity, status,
                       metadata, created_at, read_at, dismissed_at
                FROM notifications
                WHERE project_id = %s AND status != 'dismissed'
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (project_id, limit, offset),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, task_id, type, title, message, severity, status,
                       metadata, created_at, read_at, dismissed_at
                FROM notifications
                WHERE project_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
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
            """
            SELECT COUNT(*) FROM notifications
            WHERE project_id = %s AND status = 'pending'
            """,
            (project_id,),
        )
        row = cur.fetchone()

    return row[0] if row else 0


def mark_as_read(notification_id: str) -> dict[str, Any] | None:
    """Mark a notification as read.

    Returns:
        Updated notification dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE notifications
            SET status = 'read', read_at = NOW()
            WHERE id = %s
            RETURNING id, project_id, task_id, type, title, message, severity, status,
                      metadata, created_at, read_at, dismissed_at
            """,
            (notification_id,),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def dismiss_notification(notification_id: str) -> dict[str, Any] | None:
    """Dismiss a notification.

    Returns:
        Updated notification dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE notifications
            SET status = 'dismissed', dismissed_at = NOW()
            WHERE id = %s
            RETURNING id, project_id, task_id, type, title, message, severity, status,
                      metadata, created_at, read_at, dismissed_at
            """,
            (notification_id,),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def dismiss_all_for_project(project_id: str) -> int:
    """Dismiss all notifications for a project.

    Returns:
        Number of notifications dismissed
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE notifications
            SET status = 'dismissed', dismissed_at = NOW()
            WHERE project_id = %s AND status != 'dismissed'
            """,
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


def create_task_failure_notification(
    project_id: str,
    task_id: str,
    task_title: str,
    error_message: str,
    criterion_id: str | None = None,
) -> dict[str, Any]:
    """Create a notification for task failure.

    This is a convenience function for the common case of task failures.

    Args:
        project_id: Project ID
        task_id: Failed task ID
        task_title: Task title for notification
        error_message: Error message from task
        criterion_id: Optional criterion ID that failed

    Returns:
        Created notification dict
    """
    title = f"Task Failed: {task_title}"
    message = error_message

    metadata = {"criterion_id": criterion_id} if criterion_id else {}

    return create_notification(
        project_id=project_id,
        notification_type="task_failed",
        title=title,
        message=message,
        severity="error",
        task_id=task_id,
        metadata=metadata,
    )


def _row_to_dict(row: tuple) -> dict[str, Any]:
    """Convert a database row to a notification dict."""
    return {
        "id": row[0],
        "project_id": row[1],
        "task_id": row[2],
        "type": row[3],
        "title": row[4],
        "message": row[5],
        "severity": row[6],
        "status": row[7],
        "metadata": row[8] or {},
        "created_at": row[9],
        "read_at": row[10],
        "dismissed_at": row[11],
    }
