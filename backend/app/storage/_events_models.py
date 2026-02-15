"""Data models and utilities for events storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypedDict

EventLevel = Literal["error", "warning", "info", "debug"]
EventVisibility = Literal["user", "internal", "debug"]


class EventCreate(TypedDict, total=False):
    """Input for creating an event."""

    project_id: str
    trace_id: str
    span_id: str | None
    parent_span_id: str | None
    event_type: str
    name: str | None
    source: str
    level: EventLevel
    visibility: EventVisibility
    message: str | None
    attributes: dict[str, Any]


class Event(TypedDict):
    """Event record from database."""

    id: str
    project_id: str
    trace_id: str
    span_id: str | None
    parent_span_id: str | None
    event_type: str
    name: str | None
    source: str
    level: EventLevel
    visibility: EventVisibility
    message: str | None
    attributes: dict[str, Any]
    timestamp: datetime


class EventsQueryResult(TypedDict):
    """Result of events query with summary stats."""

    events: list[Event]
    total: int
    summary: dict[str, int]


def row_to_event(row: tuple[Any, ...]) -> Event:
    """Convert a database row to an Event TypedDict.

    Args:
        row: Database row with columns in standard order:
            (id, project_id, trace_id, span_id, parent_span_id,
             event_type, name, source, level, visibility,
             message, attributes, timestamp)

    Returns:
        Event TypedDict
    """
    return Event(
        id=str(row[0]),
        project_id=row[1],
        trace_id=row[2],
        span_id=row[3],
        parent_span_id=row[4],
        event_type=row[5],
        name=row[6],
        source=row[7],
        level=row[8],
        visibility=row[9],
        message=row[10],
        attributes=row[11] or {},
        timestamp=row[12],
    )
