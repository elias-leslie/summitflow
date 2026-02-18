"""Notifications helpers - shared types, constants, and row conversion."""

from __future__ import annotations

from typing import Any, Literal

from psycopg.rows import TupleRow

NotificationType = Literal["task_failed", "task_needs_input", "task_completed", "system"]
NotificationSeverity = Literal["info", "warning", "error", "critical"]
NotificationStatus = Literal["pending", "read", "dismissed"]


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
