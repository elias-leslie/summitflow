"""Notifications storage layer - Notification CRUD and status management.

Query helpers live in notifications_query.py; shared types in notifications_helpers.py.
Factory functions (task_failed, task_completed) live in notifications_write.py.
"""

from __future__ import annotations

import json
from typing import Any

from ..logging_config import get_logger
from .connection import generate_prefixed_id, get_connection, get_cursor
from .notifications_helpers import (
    NotificationSeverity,
    NotificationStatus,
    NotificationType,
    _row_to_dict,
)
from .notifications_query import (
    cleanup_old_notifications,
    get_notification,
    get_pending_count,
    list_notifications,
)
from .notifications_write import (
    create_task_completion_notification,
    create_task_failure_notification,
    delete_notification,
    dismiss_all_for_project,
    dismiss_notification,
    mark_as_read,
)

logger = get_logger(__name__)

_SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "error": 2, "critical": 3}
_SYSTEM_COOLDOWN_MINUTES = 30  # system notifications dedup at 30min (vs 15 for task notifications)

__all__ = [
    "NotificationSeverity",
    "NotificationStatus",
    "NotificationType",
    "cleanup_old_notifications",
    "create_notification",
    "create_task_completion_notification",
    "create_task_failure_notification",
    "delete_notification",
    "dismiss_all_for_project",
    "dismiss_notification",
    "get_notification",
    "get_pending_count",
    "list_notifications",
    "mark_as_read",
]


def _is_duplicate(
    project_id: str,
    notification_type: NotificationType,
    severity: NotificationSeverity,
    task_id: str | None = None,
    cooldown_minutes: int = 15,
    dedupe_key: str | None = None,
) -> bool:
    """Check for a recent identical notification; returns True if it is a dup.

    System notifications use the existing longer cooldown window. An optional
    producer key separates distinct event streams without changing defaults.
    """
    if notification_type == "system":
        cooldown_minutes = _SYSTEM_COOLDOWN_MINUTES
    current_rank = _SEVERITY_RANK.get(severity, 0)
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT severity FROM notifications
            WHERE project_id = %s AND type = %s AND task_id IS NOT DISTINCT FROM %s
              AND created_at > NOW() - (%s * INTERVAL '1 minute')
              AND status != 'dismissed'
              AND (%s::text IS NULL OR metadata->>'dedupe_key' = %s)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id, notification_type, task_id, cooldown_minutes, dedupe_key, dedupe_key),
        )
        row = cur.fetchone()
    if not row:
        return False
    return current_rank <= _SEVERITY_RANK.get(row[0], 0)


def _insert_notification(
    notification_id: str, project_id: str, notification_type: NotificationType,
    title: str, message: str, severity: NotificationSeverity,
    task_id: str | None, user_email: str | None, meta: dict[str, Any],
) -> dict[str, Any]:
    """Execute the INSERT and return the created notification dict."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notifications
              (id, project_id, task_id, user_email, type, title, message, severity, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id, project_id, task_id, user_email, type, title, message, severity, status,
                      metadata, created_at, read_at, dismissed_at
            """,
            (notification_id, project_id, task_id, user_email,
             notification_type, title, message, severity, json.dumps(meta)),
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
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    """Create a new notification, or return {} if deduplicated."""
    if _is_duplicate(project_id, notification_type, severity, task_id, dedupe_key=dedupe_key):
        logger.debug(
            "Notification deduplicated: type=%s task_id=%s severity=%s",
            notification_type, task_id, severity,
        )
        return {}
    meta = {**(metadata or {})}
    if dedupe_key is not None:
        meta["dedupe_key"] = dedupe_key
    return _insert_notification(
        generate_prefixed_id("notif"), project_id, notification_type,
        title, message, severity, task_id, user_email, meta,
    )
