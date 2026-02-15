"""Storage layer for unified execution events."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

from ._events_models import (
    Event,
    EventCreate,
    EventLevel,
    EventsQueryResult,
    EventVisibility,
    row_to_event,
)
from ._events_query import get_events_by_trace, get_events_with_filters
from .connection import get_connection

# Re-export all public types and functions for backward compatibility
__all__ = [
    "Event",
    "EventCreate",
    "EventLevel",
    "EventVisibility",
    "EventsQueryResult",
    "create_event",
    "generate_span_id",
    "get_events_by_trace",
    "get_events_with_filters",
    "log_task_event",
]

logger = logging.getLogger(__name__)


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

        return row_to_event(row)


def log_task_event(
    task_id: str,
    message: str,
    *,
    source: str = "system",
    level: EventLevel = "info",
    event_type: str = "log",
    visibility: EventVisibility = "user",
    attributes: dict[str, Any] | None = None,
) -> Event | None:
    """Log an event for a task (simpler API for progress logging).

    This is a convenience wrapper around create_event that automatically
    looks up the project_id from the task.

    Args:
        task_id: Task ID (used as trace_id)
        message: Human-readable log message
        source: Event source (system, worker, orchestrator, etc)
        level: Log level (info, warning, error, debug)
        event_type: Type of event (log, progress, state_change, etc)
        visibility: Visibility scope (user, internal, debug)
        attributes: Optional structured metadata

    Returns:
        Created Event or None if task not found
    """
    from .tasks.core import get_task

    task = get_task(task_id)
    if not task:
        logger.warning("Task %s not found, cannot log event", task_id)
        return None

    project_id = task["project_id"]

    return create_event(
        project_id=project_id,
        trace_id=task_id,
        event_type=event_type,
        source=source,
        level=level,
        visibility=visibility,
        message=message,
        attributes=attributes,
    )
