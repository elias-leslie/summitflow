"""Events API endpoints for querying execution events."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query

from ..storage.events import (
    Event,
    EventLevel,
    EventsQueryResult,
    EventVisibility,
    get_events_by_trace,
    get_events_with_filters,
)

router = APIRouter()


def _serialize_event(e: Event, include_trace_id: bool = False) -> dict[str, Any]:
    """Serialize an event row to API response format."""
    result: dict[str, Any] = {
        "id": e["id"],
        "span_id": e["span_id"],
        "parent_span_id": e["parent_span_id"],
        "event_type": e["event_type"],
        "name": e["name"],
        "source": e["source"],
        "level": e["level"],
        "visibility": e["visibility"],
        "message": e["message"],
        "attributes": e["attributes"],
        "timestamp": e["timestamp"].isoformat(),
    }
    if include_trace_id:
        result["trace_id"] = e["trace_id"]
    return result


@router.get("/projects/{project_id}/events")
async def get_events(
    project_id: str,
    trace_id: Annotated[str | None, Query(description="Filter by trace ID (task_id)")] = None,
    level: Annotated[EventLevel | None, Query(description="Filter by level")] = None,
    source: Annotated[str | None, Query(description="Filter by source")] = None,
    visibility: Annotated[EventVisibility | None, Query(description="Filter by visibility")] = None,
    search: Annotated[str | None, Query(description="Search in message")] = None,
    after: Annotated[datetime | None, Query(description="Only events after this timestamp (ISO 8601)")] = None,
    event_type: Annotated[str | None, Query(description="Filter by event_type")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Get events for a project with optional filters.

    Returns events with summary statistics (total count, by_level breakdown).
    """
    result: EventsQueryResult = await asyncio.to_thread(
        get_events_with_filters,
        project_id=project_id,
        trace_id=trace_id,
        source=source,
        level=level,
        visibility=visibility,
        search=search,
        after=after,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return {
        "events": [_serialize_event(e, include_trace_id=True) for e in result["events"]],
        "total": result["total"],
        "summary": result["summary"],
        "limit": limit,
        "offset": offset,
    }


@router.get("/projects/{project_id}/events/by-trace/{trace_id}")
async def get_events_for_trace(
    project_id: str,
    trace_id: str,
    visibility: Annotated[EventVisibility | None, Query(description="Filter by visibility")] = None,
    level: Annotated[EventLevel | None, Query(description="Filter by level")] = None,
    after: Annotated[datetime | None, Query(description="Only events after this timestamp (ISO 8601)")] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
) -> dict[str, Any]:
    """Get all events for a specific trace (execution run).

    Optimized for fetching a complete execution timeline.
    Returns events ordered by timestamp ascending.
    Supports time-range pagination via `after` parameter.
    """
    events: list[Event] = await asyncio.to_thread(
        get_events_by_trace,
        trace_id=trace_id,
        visibility=visibility,
        level=level,
        after=after,
        limit=limit,
    )
    return {
        "trace_id": trace_id,
        "events": [_serialize_event(e) for e in events],
        "count": len(events),
    }
