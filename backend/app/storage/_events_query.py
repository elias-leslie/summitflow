"""Query operations for events storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._events_models import Event, EventLevel, EventsQueryResult, EventVisibility, row_to_event
from .connection import get_connection


def get_events_by_trace(
    trace_id: str,
    *,
    visibility: EventVisibility | None = None,
    level: EventLevel | None = None,
    after: datetime | None = None,
    from_sequence: int | None = None,
    limit: int = 1000,
) -> list[Event]:
    """Get events for a specific trace (execution run).

    Args:
        trace_id: Trace ID to query
        visibility: Optional visibility filter
        level: Optional level filter
        after: Only return events after this timestamp
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

    if after is not None:
        conditions.append("timestamp > %s")
        params.append(after)

    params.append(limit)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, project_id, trace_id, span_id, parent_span_id,
                   event_type, name, source, level, visibility,
                   message, attributes, timestamp
            FROM events
            WHERE {" AND ".join(conditions)}
            ORDER BY timestamp ASC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
        return [row_to_event(row) for row in rows]


def get_events_with_filters(
    project_id: str,
    *,
    trace_id: str | None = None,
    source: str | None = None,
    level: EventLevel | None = None,
    visibility: EventVisibility | None = None,
    search: str | None = None,
    after: datetime | None = None,
    event_type: str | None = None,
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
        after: Only return events after this timestamp
        event_type: Optional event_type filter
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

    if after is not None:
        conditions.append("timestamp > %s")
        params.append(after)

    if event_type is not None:
        conditions.append("event_type = %s")
        params.append(event_type)

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

        events = [row_to_event(row) for row in rows]

        return EventsQueryResult(
            events=events,
            total=total,
            summary=summary,
        )
