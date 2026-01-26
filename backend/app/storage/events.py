"""Storage layer for unified execution events."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

from psycopg.types.json import Jsonb

from .connection import get_connection

logger = logging.getLogger(__name__)

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


def generate_span_id() -> str:
    """Generate a unique span ID (16 hex chars like OTel)."""
    return uuid.uuid4().hex[:16]


def create_event(
    project_id: str,
    trace_id: str,
    event_type: str,
    source: str,
    *,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    name: str | None = None,
    level: EventLevel = "info",
    visibility: EventVisibility = "user",
    message: str | None = None,
    attributes: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> Event:
    """Create a new event in the database.

    Args:
        project_id: Project this event belongs to
        trace_id: Trace ID (typically task_id for execution events)
        event_type: Type of event (state_change, progress, error, log, etc)
        source: Event source (orchestrator, worker, agent, system)
        span_id: Optional span ID (auto-generated if not provided)
        parent_span_id: Optional parent span for hierarchy
        name: Optional event name
        level: Log level (error, warning, info, debug)
        visibility: Visibility scope (user, internal, debug)
        message: Human-readable message
        attributes: Structured metadata
        timestamp: Event timestamp (defaults to now)

    Returns:
        Created Event record
    """
    if span_id is None:
        span_id = generate_span_id()
    if attributes is None:
        attributes = {}
    if timestamp is None:
        timestamp = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO events (
                project_id, trace_id, span_id, parent_span_id,
                event_type, name, source, level, visibility,
                message, attributes, timestamp
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING id, project_id, trace_id, span_id, parent_span_id,
                      event_type, name, source, level, visibility,
                      message, attributes, timestamp
            """,
            (
                project_id,
                trace_id,
                span_id,
                parent_span_id,
                event_type,
                name,
                source,
                level,
                visibility,
                message,
                Jsonb(attributes),
                timestamp,
            ),
        )
        row = cur.fetchone()
        conn.commit()

        if row is None:
            raise RuntimeError("Failed to create event")

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


def get_events_by_trace(
    trace_id: str,
    *,
    visibility: EventVisibility | None = None,
    level: EventLevel | None = None,
    from_sequence: int | None = None,
    limit: int = 1000,
) -> list[Event]:
    """Get events for a specific trace (execution run).

    Args:
        trace_id: Trace ID to query
        visibility: Optional visibility filter
        level: Optional level filter
        from_sequence: Optional starting timestamp for pagination
        limit: Max events to return

    Returns:
        List of Event records ordered by timestamp
    """
    conditions = ["trace_id = %s"]
    params: list[Any] = [trace_id]

    if visibility is not None:
        conditions.append("visibility = %s")
        params.append(visibility)

    if level is not None:
        conditions.append("level = %s")
        params.append(level)

    params.append(limit)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, project_id, trace_id, span_id, parent_span_id,
                   event_type, name, source, level, visibility,
                   message, attributes, timestamp
            FROM events
            WHERE {' AND '.join(conditions)}
            ORDER BY timestamp ASC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()

        return [
            Event(
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
            for row in rows
        ]


class EventsQueryResult(TypedDict):
    """Result of events query with summary stats."""

    events: list[Event]
    total: int
    summary: dict[str, int]


def get_events_with_filters(
    project_id: str,
    *,
    trace_id: str | None = None,
    source: str | None = None,
    level: EventLevel | None = None,
    visibility: EventVisibility | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> EventsQueryResult:
    """Query events with filters and summary stats.

    Args:
        project_id: Project to query
        trace_id: Optional trace filter
        source: Optional source filter
        level: Optional level filter
        visibility: Optional visibility filter
        search: Optional text search in message
        limit: Max events per page
        offset: Pagination offset

    Returns:
        EventsQueryResult with events, total count, and by_level summary
    """
    conditions = ["project_id = %s"]
    params: list[Any] = [project_id]

    if trace_id is not None:
        conditions.append("trace_id = %s")
        params.append(trace_id)

    if source is not None:
        conditions.append("source = %s")
        params.append(source)

    if level is not None:
        conditions.append("level = %s")
        params.append(level)

    if visibility is not None:
        conditions.append("visibility = %s")
        params.append(visibility)

    if search is not None:
        conditions.append("message ILIKE %s")
        params.append(f"%{search}%")

    where_clause = " AND ".join(conditions)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) FROM events WHERE {where_clause}
            """,
            params,
        )
        count_row = cur.fetchone()
        total = count_row[0] if count_row else 0

        cur.execute(
            f"""
            SELECT level, COUNT(*) FROM events
            WHERE {where_clause}
            GROUP BY level
            """,
            params,
        )
        summary = {row[0]: row[1] for row in cur.fetchall()}

        query_params = [*params, limit, offset]
        cur.execute(
            f"""
            SELECT id, project_id, trace_id, span_id, parent_span_id,
                   event_type, name, source, level, visibility,
                   message, attributes, timestamp
            FROM events
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT %s OFFSET %s
            """,
            query_params,
        )
        rows = cur.fetchall()

        events = [
            Event(
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
            for row in rows
        ]

        return EventsQueryResult(
            events=events,
            total=total,
            summary=summary,
        )
