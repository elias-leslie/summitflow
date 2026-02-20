"""Notifications storage layer - Notification CRUD and status management.

This module provides data access for notification alerts.
Query helpers live in notifications_query.py; shared types in notifications_helpers.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .connection import generate_prefixed_id, get_connection
from .notifications_helpers import (
    NotificationSeverity,
    NotificationStatus,
    NotificationType,
    _row_to_dict,
)
from .notifications_query import (
    get_notification,
    get_notifications_by_user_email,
    get_pending_count,
    list_notifications,
)
from .notifications_write import (
    delete_notification,
    dismiss_all_for_project,
    dismiss_notification,
    mark_as_read,
)

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[None]] = set()

# Re-export type aliases for backward compatibility
__all__ = [
    "NotificationSeverity",
    "NotificationStatus",
    "NotificationType",
    "create_notification",
    "create_task_completion_notification",
    "create_task_failure_notification",
    "delete_notification",
    "dismiss_all_for_project",
    "dismiss_notification",
    "get_notification",
    "get_notifications_by_user_email",
    "get_pending_count",
    "list_notifications",
    "mark_as_read",
]


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

    existing_rank = severity_rank.get(row[0], 0)
    return current_rank <= existing_rank


def _schedule_delivery(notification: dict[str, Any]) -> None:
    """Fire-and-forget push delivery for a notification.

    Checks for a running asyncio loop and schedules delivery as a task.
    Storage layer is sync, so this bridges into the async delivery service.
    """
    from app.config import settings

    if not settings.vapid_public_key:
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


def _insert_notification(
    notification_id: str,
    project_id: str,
    notification_type: NotificationType,
    title: str,
    message: str,
    severity: NotificationSeverity,
    task_id: str | None,
    user_email: str | None,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Execute the INSERT and return the created notification dict."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notifications (id, project_id, task_id, user_email, type, title, message, severity, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id, project_id, task_id, user_email, type, title, message, severity, status,
                      metadata, created_at, read_at, dismissed_at
            """,
            (notification_id, project_id, task_id, user_email, notification_type, title, message, severity, json.dumps(meta)),
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)


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
    """Create a new notification, or return {} if deduplicated."""
    if _is_duplicate(project_id, notification_type, severity, task_id):
        logger.debug(
            "Notification deduplicated: type=%s task_id=%s severity=%s",
            notification_type,
            task_id,
            severity,
        )
        return {}
    notification = _insert_notification(
        _generate_notification_id(), project_id, notification_type,
        title, message, severity, task_id, user_email, metadata or {},
    )
    _schedule_delivery(notification)
    return notification


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

    Uses severity 'warning' to trigger push delivery (info stays in-app only).

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
