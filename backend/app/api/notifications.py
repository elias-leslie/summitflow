"""Notifications API - REST endpoints for notification management.

This module provides:
- List notifications for a project or across all projects
- Get pending notification count (per project or global)
- Mark notifications as read/dismissed
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from ..storage import notifications as notification_store
from ..storage._sql import static_sql
from ..storage.connection import get_connection, get_cursor
from ..storage.notifications_helpers import (
    NotificationSeverity,
    NotificationType,
    _row_to_dict,
)

router = APIRouter(tags=["Notifications"])


# ============================================================================
# Request/Response Models
# ============================================================================


class NotificationResponse(BaseModel):
    """Notification response model."""

    id: str
    project_id: str
    task_id: str | None
    type: str
    title: str
    message: str
    severity: str
    status: str
    metadata: dict[str, Any]
    created_at: str | None
    read_at: str | None
    dismissed_at: str | None


class NotificationListResponse(BaseModel):
    """Response for listing notifications."""

    items: list[NotificationResponse]
    total: int
    pending_count: int


class NotificationCountResponse(BaseModel):
    """Response for notification count."""

    pending: int


class CreateNotificationRequest(BaseModel):
    """Request to create a notification."""

    type: NotificationType
    title: str
    message: str
    severity: NotificationSeverity = "info"
    task_id: str | None = None
    metadata: dict[str, Any] | None = None
    dedupe_key: str | None = None


# ============================================================================
# Helpers
# ============================================================================

_NOTIFICATION_COLUMNS = (
    "id, project_id, task_id, user_email, type, title, message, severity, status,"
    " metadata, created_at, read_at, dismissed_at"
)


def _scope_filter(
    project_id: str | None,
    status_filter: str | None,
    include_dismissed: bool,
) -> tuple[str, list[Any]]:
    """Build a static WHERE clause shared by list and total queries."""
    clauses: list[str] = []
    params: list[Any] = []
    if project_id is not None:
        clauses.append("project_id = %s")
        params.append(project_id)
    if status_filter:
        clauses.append("status = %s")
        params.append(status_filter)
    elif not include_dismissed:
        clauses.append("status != 'dismissed'")
    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), params


def _query_notifications(
    project_id: str | None,
    status_filter: str | None,
    include_dismissed: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int, int]:
    """Return (page, total matching, pending count) for one project or all projects."""
    where, params = _scope_filter(project_id, status_filter, include_dismissed)
    pending_where, pending_params = _scope_filter(project_id, "pending", False)
    with get_cursor() as cur:
        cur.execute(
            static_sql(
                f"SELECT {_NOTIFICATION_COLUMNS} FROM notifications {where}"
                " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            ),
            [*params, limit, offset],
        )
        rows = cur.fetchall()
        cur.execute(static_sql(f"SELECT COUNT(*) FROM notifications {where}"), params)
        total_row = cur.fetchone()
        cur.execute(static_sql(f"SELECT COUNT(*) FROM notifications {pending_where}"), pending_params)
        pending_row = cur.fetchone()
    return (
        [_row_to_dict(row) for row in rows],
        int(total_row[0]) if total_row else 0,
        int(pending_row[0]) if pending_row else 0,
    )


def _global_pending_count() -> int:
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM notifications WHERE status = 'pending'")
        row = cur.fetchone()
    return int(row[0]) if row else 0


def _dismiss_all_global() -> int:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE notifications SET status = 'dismissed', dismissed_at = NOW() WHERE status != 'dismissed'"
        )
        count = cur.rowcount
        conn.commit()
    return count



def _get_notification_or_404(
    notification_id: str, project_id: str,
) -> dict[str, Any]:
    """Get notification and verify it belongs to the project. Raises 404 if not found."""
    notification = notification_store.get_notification(notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail=f"Notification {notification_id} not found")
    if notification["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Notification {notification_id} not found in project {project_id}",
        )
    return notification


def _notification_to_response(notification: dict[str, Any]) -> NotificationResponse:
    """Convert storage notification to API response."""
    return NotificationResponse(
        id=notification["id"],
        project_id=notification["project_id"],
        task_id=notification.get("task_id"),
        type=notification["type"],
        title=notification["title"],
        message=notification["message"],
        severity=notification["severity"],
        status=notification["status"],
        metadata=notification.get("metadata", {}),
        created_at=notification["created_at"].isoformat()
        if notification.get("created_at")
        else None,
        read_at=notification["read_at"].isoformat() if notification.get("read_at") else None,
        dismissed_at=notification["dismissed_at"].isoformat()
        if notification.get("dismissed_at")
        else None,
    )


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/projects/{project_id}/notifications", response_model=NotificationListResponse)
async def list_notifications(
    project_id: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    include_dismissed: bool = False,
) -> NotificationListResponse:
    """List notifications for a project.

    Args:
        project_id: Project ID
        status: Filter by status (pending, read, dismissed)
        limit: Max results (default 50)
        offset: Result offset
        include_dismissed: Include dismissed notifications (default False)
    """
    notifications, total, pending_count = _query_notifications(
        project_id, status, include_dismissed, limit, offset,
    )
    return NotificationListResponse(
        items=[_notification_to_response(n) for n in notifications],
        total=total,
        pending_count=pending_count,
    )


@router.get("/notifications", response_model=NotificationListResponse)
async def list_all_notifications(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    include_dismissed: bool = False,
) -> NotificationListResponse:
    """List notifications across all projects (top-bar bell outside project pages)."""
    notifications, total, pending_count = _query_notifications(
        None, status, include_dismissed, limit, offset,
    )
    return NotificationListResponse(
        items=[_notification_to_response(n) for n in notifications],
        total=total,
        pending_count=pending_count,
    )


@router.get("/notifications/count", response_model=NotificationCountResponse)
async def get_all_notification_count() -> NotificationCountResponse:
    """Get the pending notification count across all projects."""
    return NotificationCountResponse(pending=_global_pending_count())


@router.post("/notifications/dismiss-all", response_model=dict[str, Any])
async def dismiss_all_notifications_global() -> dict[str, Any]:
    """Dismiss every non-dismissed notification across all projects."""
    return {"dismissed": _dismiss_all_global()}


@router.get("/projects/{project_id}/notifications/count", response_model=NotificationCountResponse)
async def get_notification_count(project_id: str) -> NotificationCountResponse:
    """Get count of pending notifications for a project."""
    count = notification_store.get_pending_count(project_id)
    return NotificationCountResponse(pending=count)


@router.get(
    "/projects/{project_id}/notifications/{notification_id}", response_model=NotificationResponse
)
async def get_notification(project_id: str, notification_id: str) -> NotificationResponse:
    """Get a single notification."""
    notification = _get_notification_or_404(notification_id, project_id)
    return _notification_to_response(notification)


@router.post(
    "/projects/{project_id}/notifications",
    response_model=NotificationResponse,
    responses={204: {"description": "Deduplicated; no notification created"}},
)
async def create_notification(
    project_id: str, request: CreateNotificationRequest
) -> NotificationResponse | Response:
    """Create a new notification; 204 when an identical recent one suppresses it."""
    notification = notification_store.create_notification(
        project_id=project_id,
        notification_type=request.type,
        title=request.title,
        message=request.message,
        severity=request.severity,
        task_id=request.task_id,
        metadata=request.metadata,
        dedupe_key=request.dedupe_key,
    )
    if not notification:
        return Response(status_code=204)
    return _notification_to_response(notification)


@router.patch(
    "/projects/{project_id}/notifications/{notification_id}/read",
    response_model=NotificationResponse,
)
async def mark_notification_read(project_id: str, notification_id: str) -> NotificationResponse:
    """Mark a notification as read."""
    _get_notification_or_404(notification_id, project_id)
    notification = notification_store.mark_as_read(notification_id)
    if not notification:
        raise HTTPException(status_code=500, detail="Failed to mark notification as read")
    return _notification_to_response(notification)


@router.patch(
    "/projects/{project_id}/notifications/{notification_id}/dismiss",
    response_model=NotificationResponse,
)
async def dismiss_notification(project_id: str, notification_id: str) -> NotificationResponse:
    """Dismiss a notification."""
    _get_notification_or_404(notification_id, project_id)
    notification = notification_store.dismiss_notification(notification_id)
    if not notification:
        raise HTTPException(status_code=500, detail="Failed to dismiss notification")
    return _notification_to_response(notification)


@router.post("/projects/{project_id}/notifications/dismiss-all", response_model=dict[str, Any])
async def dismiss_all_notifications(project_id: str) -> dict[str, Any]:
    """Dismiss all notifications for a project."""
    count = notification_store.dismiss_all_for_project(project_id)
    return {"dismissed": count}


@router.delete(
    "/projects/{project_id}/notifications/{notification_id}", response_model=dict[str, Any]
)
async def delete_notification(project_id: str, notification_id: str) -> dict[str, Any]:
    """Delete a notification."""
    _get_notification_or_404(notification_id, project_id)
    if not notification_store.delete_notification(notification_id):
        raise HTTPException(status_code=500, detail="Failed to delete notification")
    return {"deleted": True, "id": notification_id}
