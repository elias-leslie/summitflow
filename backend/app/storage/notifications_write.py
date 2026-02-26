"""Notifications write layer - status updates, deletion, and factory functions."""

from __future__ import annotations

from typing import Any

from .connection import get_connection
from .notifications_helpers import _row_to_dict

_RETURNING_COLS = (
    "RETURNING id, project_id, task_id, user_email, type, title, message, severity, status,"
    " metadata, created_at, read_at, dismissed_at"
)


def mark_as_read(notification_id: str) -> dict[str, Any] | None:
    """Mark a notification as read. Returns updated dict or None if not found."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE notifications SET status = 'read', read_at = NOW() WHERE id = %s {_RETURNING_COLS}",
            (notification_id,),
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row) if row else None


def dismiss_notification(notification_id: str) -> dict[str, Any] | None:
    """Dismiss a notification. Returns updated dict or None if not found."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE notifications SET status = 'dismissed', dismissed_at = NOW() WHERE id = %s {_RETURNING_COLS}",
            (notification_id,),
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row) if row else None


def dismiss_all_for_project(project_id: str) -> int:
    """Dismiss all pending notifications for a project. Returns count dismissed."""
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
    """Delete a notification. Returns True if deleted, False if not found."""
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
    subtask_id: str | None = None,
    recommendation: str | None = None,
    blocker_summary: str | None = None,
) -> dict[str, Any]:
    """Create a task-failure notification with Johnny's voice."""
    from .notifications import create_notification

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
    if subtask_id:
        metadata["subtask_id"] = subtask_id
    if recommendation:
        metadata["recommendation"] = recommendation
    if blocker_summary:
        metadata["blocker_summary"] = blocker_summary
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
    """Create a task-completion notification with Johnny's voice.

    Uses severity 'warning' to trigger push delivery (info stays in-app only).
    """
    from .notifications import create_notification

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
