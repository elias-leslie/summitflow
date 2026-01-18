"""Activity API - Unified activity feed endpoint.

Provides:
- GET /api/activity - Paginated activity feed from all sources
"""

from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..storage import activity as activity_store

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class ActivityEventMetadata(BaseModel):
    """Metadata for an activity event, varies by type."""

    task_id: str | None = None
    session_id: str | None = None
    backup_id: str | None = None
    commit_sha: str | None = None
    status: str | None = None
    title: str | None = None
    agent_type: str | None = None
    backup_type: str | None = None
    size_bytes: int | None = None
    tests_passed: int | None = None
    tests_failed: int | None = None
    notes: str | None = None


class ActivityEvent(BaseModel):
    """A single activity event."""

    type: Literal["task", "session", "backup", "git"]
    message: str
    timestamp: str | None
    project_id: str
    metadata: dict[str, Any]


class ActivityFeedResponse(BaseModel):
    """Response for activity feed."""

    items: list[ActivityEvent]
    total: int
    limit: int
    offset: int
    has_more: bool


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/activity")
async def get_activity_feed(
    project_id: str | None = Query(default=None, description="Filter by project ID"),
    limit: int = Query(default=50, le=100, ge=1, description="Max events per page"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    types: str | None = Query(
        default=None,
        description="Comma-separated event types: task,session,backup,git",
    ),
) -> ActivityFeedResponse:
    """Get unified activity feed from all sources.

    Aggregates:
    - Task completions (status changes to completed/cancelled/blocked)
    - Agent sessions (completed/failed sessions)
    - Backup events (completed/failed backups)
    - Git commits (tracked via agent sessions)

    Results are sorted by timestamp (newest first) and paginated.
    """
    # Parse event types filter
    event_types: list[str] | None = None
    if types:
        event_types = [t.strip() for t in types.split(",") if t.strip()]
        valid_types = {"task", "session", "backup", "git"}
        event_types = [t for t in event_types if t in valid_types]
        if not event_types:
            event_types = None

    events, total = activity_store.get_aggregated_activity(
        project_id=project_id,
        limit=limit,
        offset=offset,
        event_types=event_types,
    )

    return ActivityFeedResponse(
        items=[
            ActivityEvent(
                type=e["type"],
                message=e["message"],
                timestamp=e["timestamp"],
                project_id=e["project_id"],
                metadata=e["metadata"],
            )
            for e in events
        ],
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(events) < total,
    )
