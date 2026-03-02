"""Query operations for events storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._events_models import Event, EventLevel, EventsQueryResult, EventVisibility, row_to_event
from .connection import get_connection

_SELECT_COLUMNS = """
    SELECT id, project_id, trace_id, span_id, parent_span_id,
           event_type, name, source, level, visibility,
           message, attributes, timestamp
    FROM events
"""


def _build_trace_conditions(
    trace_id: str,
    visibility: EventVisibility | None,
    level: EventLevel | None,
    after: datetime | None,
) -> tuple[list[str], list[Any]]:
    """Build WHERE conditions and params for get_events_by_trace."""
    conditions: list[str] = ["trace_id = %s"]
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

    return conditions, params


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
    conditions, params = _build_trace_conditions(trace_id, visibility, level, after)
    params.append(limit)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"{_SELECT_COLUMNS}WHERE {' AND '.join(conditions)}"
            " ORDER BY timestamp ASC LIMIT %s",
            params,
        )
        rows = cur.fetchall()
        return [row_to_event(row) for row in rows]


def _build_filter_conditions(
    project_id: str,
    trace_id: str | None,
    source: str | None,
    level: EventLevel | None,
    visibility: EventVisibility | None,
    search: str | None,
    after: datetime | None,
    event_type: str | None,
) -> tuple[list[str], list[Any]]:
    """Build WHERE conditions and params for get_events_with_filters."""
    conditions: list[str] = ["project_id = %s"]
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

    return conditions, params


def _fetch_events_stats(
    cur: Any, where_clause: str, params: list[Any]
) -> tuple[int, dict[str, int]]:
    """Run COUNT and GROUP BY level queries; return (total, summary)."""
    cur.execute(
        f"SELECT COUNT(*) FROM events WHERE {where_clause}",
        params,
    )
    count_row = cur.fetchone()
    total: int = count_row[0] if count_row else 0

    cur.execute(
        f"SELECT level, COUNT(*) FROM events WHERE {where_clause} GROUP BY level",
        params,
    )
    summary: dict[str, int] = {row[0]: row[1] for row in cur.fetchall()}

    return total, summary


def _fetch_events_page(
    cur: Any, where_clause: str, params: list[Any], limit: int, offset: int
) -> list[Event]:
    """Run paginated SELECT for events; return list of Event records."""
    query_params = [*params, limit, offset]
    cur.execute(
        f"{_SELECT_COLUMNS}WHERE {where_clause}"
        " ORDER BY timestamp DESC LIMIT %s OFFSET %s",
        query_params,
    )
    return [row_to_event(row) for row in cur.fetchall()]


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
    conditions, params = _build_filter_conditions(
        project_id, trace_id, source, level, visibility, search, after, event_type
    )
    where_clause = " AND ".join(conditions)

    with get_connection() as conn, conn.cursor() as cur:
        total, summary = _fetch_events_stats(cur, where_clause, params)
        events = _fetch_events_page(cur, where_clause, params, limit, offset)

    return EventsQueryResult(events=events, total=total, summary=summary)
