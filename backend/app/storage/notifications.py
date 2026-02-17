"""Notifications storage layer - Notification CRUD and status management.

This module provides data access for notification alerts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from psycopg.rows import TupleRow

from .connection import generate_prefixed_id, get_connection

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[None]] = set()

NotificationType = Literal["task_failed", "task_needs_input", "task_completed", "system"]
NotificationSeverity = Literal["info", "warning", "error", "critical"]
NotificationStatus = Literal["pending", "read", "dismissed"]


def _generate_notification_id() -> str:
    """Generate a unique notification ID."""
    return generate_prefixed_id("notif")


def _is_duplicate(
    project_id: str,
    notification_type: NotificationType,
    severity: NotificationSeverity,
    task_id: str | None = None,
    cooldown_minutes: int = 15,
) -> bool:
    """Check if a similar notification was created within the cooldown window.

    Dedup rules:
    - Same type + task_id + severity within cooldown → duplicate
    - Severity escalation (e.g., warning → error for same task) is NOT a dup
    - System notifications are never deduped (rare, intentional)
    """
    if notification_type == "system":
        return False

    severity_rank = {"info": 0, "warning": 1, "error": 2, "critical": 3}
    current_rank = severity_rank.get(severity, 0)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT severity FROM notifications
            WHERE project_id = %s AND type = %s AND task_id IS NOT DISTINCT FROM %s
              AND created_at > NOW() - INTERVAL '%s minutes'
              AND status != 'dismissed'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id, notification_type, task_id, cooldown_minutes),
        )
        row = cur.fetchone()

    if not row:
        return False

    # Allow severity escalation
    existing_rank = severity_rank.get(row[0], 0)
    return current_rank <= existing_rank


def create_notification(
    project_id: str,
    notification_type: NotificationType,
    title: str,
    message: str,
    severity: NotificationSeverity = "info",
    task_id: str | None = None,
    user_email: str | None = None,
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
        user_email: Optional user email for user-specific notifications
        metadata: Optional additional metadata

    Returns:
        Created notification dict, or empty dict if deduplicated
    """
    import json

    # Dedup check — skip if a similar notification was sent recently
    if _is_duplicate(project_id, notification_type, severity, task_id):
        logger.debug(
            "Notification deduplicated: type=%s task_id=%s severity=%s",
            notification_type,
            task_id,
            severity,
        )
        return {}

    notification_id = _generate_notification_id()
    meta = metadata or {}

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notifications (id, project_id, task_id, user_email, type, title, message, severity, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id, project_id, task_id, user_email, type, title, message, severity, status,
                      metadata, created_at, read_at, dismissed_at
            """,
            (
                notification_id,
                project_id,
                task_id,
                user_email,
                notification_type,
                title,
                message,
                severity,
                json.dumps(meta),
            ),
        )
        row = cur.fetchone()
        conn.commit()

    notification = _row_to_dict(row)
    _schedule_delivery(notification)
    return notification


def _schedule_delivery(notification: dict[str, Any]) -> None:
    """Fire-and-forget push delivery for a notification.

    Checks for a running asyncio loop and schedules delivery as a task.
    Storage layer is sync, so this bridges into the async delivery service.
    """
    from app.config import settings

    if not settings.ntfy_enabled:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — skip push delivery (e.g., in CLI/test contexts)
        return

    async def _deliver() -> None:
        try:
            from app.services.notifications.delivery import deliver

            await deliver(notification)
        except Exception:
            logger.exception("Push delivery failed for notification %s", notification.get("id"))

    task = loop.create_task(_deliver())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def get_notification(notification_id: str) -> dict[str, Any] | None:
    """Get a notification by ID.

    Returns:
        Notification dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, task_id, user_email, type, title, message, severity, status,
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
                SELECT id, project_id, task_id, user_email, type, title, message, severity, status,
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
                SELECT id, project_id, task_id, user_email, type, title, message, severity, status,
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
                SELECT id, project_id, task_id, user_email, type, title, message, severity, status,
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
            RETURNING id, project_id, task_id, user_email, type, title, message, severity, status,
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
            RETURNING id, project_id, task_id, user_email, type, title, message, severity, status,
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
    agent_hub_session_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create a notification for task failure with Johnny's voice.

    Args:
        project_id: Project ID
        task_id: Failed task ID
        task_title: Task title for notification
        error_message: Error message from task
        criterion_id: Optional criterion ID that failed
        agent_hub_session_ids: Optional session IDs for chat context

    Returns:
        Created notification dict
    """
    title = f"Task failed: {task_title}"
    message = (
        f"I was working on '{task_title}' but hit a problem: "
        f"{error_message} Tap to chat about next steps."
    )

    metadata: dict[str, Any] = {"johnny": True}
    if criterion_id:
        metadata["criterion_id"] = criterion_id
    if agent_hub_session_ids:
        metadata["agent_hub_session_ids"] = agent_hub_session_ids

    return create_notification(
        project_id=project_id,
        notification_type="task_failed",
        title=title,
        message=message,
        severity="error",
        task_id=task_id,
        metadata=metadata,
    )


def create_task_completion_notification(
    project_id: str,
    task_id: str,
    task_title: str,
    detail: str = "",
    agent_hub_session_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create a notification for task completion with Johnny's voice.

    Uses severity 'warning' to trigger ntfy push (info stays in-app only).

    Args:
        project_id: Project ID
        task_id: Completed task ID
        task_title: Task title
        detail: Optional detail about the completion
        agent_hub_session_ids: Optional session IDs for chat context

    Returns:
        Created notification dict
    """
    title = f"Task done: {task_title}"
    suffix = f" {detail}" if detail else ""
    message = f"Finished '{task_title}' — all checks passed.{suffix} Tap to review."

    metadata: dict[str, Any] = {"johnny": True}
    if agent_hub_session_ids:
        metadata["agent_hub_session_ids"] = agent_hub_session_ids

    return create_notification(
        project_id=project_id,
        notification_type="task_completed",
        title=title,
        message=message,
        severity="warning",
        task_id=task_id,
        metadata=metadata,
    )


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
        # Build query
        if status_filter:
            cur.execute(
                """
                SELECT id, project_id, task_id, user_email, type, title, message, severity, status,
                       metadata, created_at, read_at, dismissed_at
                FROM notifications
                WHERE user_email = %s AND status = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_email, status_filter, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, task_id, user_email, type, title, message, severity, status,
                       metadata, created_at, read_at, dismissed_at
                FROM notifications
                WHERE user_email = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_email, limit),
            )

        rows = cur.fetchall()
        notifications = [_row_to_dict(row) for row in rows]

        # Mark as seen if requested
        if mark_as_seen and notifications:
            notification_ids = [n["id"] for n in notifications if n["status"] == "pending"]
            if notification_ids:
                cur.execute(
                    """
                    UPDATE notifications
                    SET status = 'read', read_at = NOW()
                    WHERE id = ANY(%s::text[])
                    """,
                    (notification_ids,),
                )
                conn.commit()

    return notifications



def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a notification dict."""
    if row is None:
        raise ValueError("Row cannot be None")
    return {
        "id": row[0],
        "project_id": row[1],
        "task_id": row[2],
        "user_email": row[3],
        "type": row[4],
        "title": row[5],
        "message": row[6],
        "severity": row[7],
        "status": row[8],
        "metadata": row[9] or {},
        "created_at": row[10],
        "read_at": row[11],
        "dismissed_at": row[12],
    }
