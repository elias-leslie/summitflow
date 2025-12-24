"""Notifications API - REST endpoints for notification management.

This module provides:
- List notifications for a project
- Get pending notification count
- Mark notifications as read/dismissed
"""

from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..storage import notifications as notification_store

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

    type: Literal["task_failed", "task_needs_input", "task_completed", "system"]
    title: str
    message: str
    severity: Literal["info", "warning", "error", "critical"] = "info"
    task_id: str | None = None
    metadata: dict[str, Any] | None = None


# ============================================================================
# Helpers
# ============================================================================


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
    notifications = notification_store.list_notifications(
        project_id=project_id,
        status_filter=cast(Literal["pending", "read", "dismissed"], status) if status else None,
        limit=limit,
        offset=offset,
        include_dismissed=include_dismissed,
    )

    pending_count = notification_store.get_pending_count(project_id)

    return NotificationListResponse(
        items=[_notification_to_response(n) for n in notifications],
        total=len(notifications),
        pending_count=pending_count,
    )


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
    notification = notification_store.get_notification(notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail=f"Notification {notification_id} not found")
    if notification["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Notification {notification_id} not found in project {project_id}",
        )
    return _notification_to_response(notification)


@router.post("/projects/{project_id}/notifications", response_model=NotificationResponse)
async def create_notification(
    project_id: str, request: CreateNotificationRequest
) -> NotificationResponse:
    """Create a new notification."""
    notification = notification_store.create_notification(
        project_id=project_id,
        notification_type=request.type,
        title=request.title,
        message=request.message,
        severity=request.severity,
        task_id=request.task_id,
        metadata=request.metadata,
    )
    return _notification_to_response(notification)


@router.patch(
    "/projects/{project_id}/notifications/{notification_id}/read",
    response_model=NotificationResponse,
)
async def mark_notification_read(project_id: str, notification_id: str) -> NotificationResponse:
    """Mark a notification as read."""
    # Verify notification exists and belongs to project
    existing = notification_store.get_notification(notification_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Notification {notification_id} not found")
    if existing["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Notification {notification_id} not found in project {project_id}",
        )

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
    # Verify notification exists and belongs to project
    existing = notification_store.get_notification(notification_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Notification {notification_id} not found")
    if existing["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Notification {notification_id} not found in project {project_id}",
        )

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
    # Verify notification exists and belongs to project
    existing = notification_store.get_notification(notification_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Notification {notification_id} not found")
    if existing["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Notification {notification_id} not found in project {project_id}",
        )

    if not notification_store.delete_notification(notification_id):
        raise HTTPException(status_code=500, detail="Failed to delete notification")
    return {"deleted": True, "id": notification_id}
