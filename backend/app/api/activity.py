"""Activity API - Unified activity feed endpoint.

Provides:
- GET /api/activity - Paginated activity feed from all sources
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..storage import activity as activity_store
from ..storage.activity.types import ActivityEvent as StorageActivityEvent

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class ActivityEvent(BaseModel):
    """A single activity event."""

    type: Literal["task", "backup", "git"]
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
# Helpers
# ============================================================================

_VALID_TYPES = {"task", "backup", "git"}


def _parse_event_types(types: str | None) -> list[str] | None:
    """Parse and validate comma-separated event type filter string."""
    if not types:
        return None
    parsed = [t.strip() for t in types.split(",") if t.strip()]
    valid = [t for t in parsed if t in _VALID_TYPES]
    return valid or None


def _to_activity_event(e: StorageActivityEvent) -> ActivityEvent:
    """Convert a raw event dict to an ActivityEvent model."""
    return ActivityEvent(
        type=e["type"],
        message=e["message"],
        timestamp=e["timestamp"],
        project_id=e["project_id"],
        metadata=e["metadata"],
    )


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
        description="Comma-separated event types: task,backup,git",
    ),
) -> ActivityFeedResponse:
    """Get unified activity feed from all sources.

    Aggregates:
    - Task changes (created, updated, completed, blocked, cancelled)
    - Backup events (completed/failed backups)
    - Git commits (read from repository history)

    Results are sorted by timestamp (newest first) and paginated.
    """
    event_types = _parse_event_types(types)
    events, total = await asyncio.to_thread(
        activity_store.get_aggregated_activity,
        project_id=project_id,
        limit=limit,
        offset=offset,
        event_types=event_types,
    )
    return ActivityFeedResponse(
        items=[_to_activity_event(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(events) < total,
    )
