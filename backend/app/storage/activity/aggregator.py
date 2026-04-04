"""Activity Aggregator - Combines events from multiple sources.

This module provides the main aggregation function that combines and sorts
activity events from all sources (tasks, sessions, backups, git).
"""

from __future__ import annotations

from datetime import datetime

from .sources import (
    get_recent_backup_events,
    get_recent_git_events,
    get_recent_task_events,
)
from .types import ActivityEvent


def _parse_event_timestamp(event: ActivityEvent) -> datetime:
    """Parse timestamp from an activity event for sorting.

    Args:
        event: Activity event with timestamp field

    Returns:
        Parsed datetime, or datetime.min if parsing fails
    """
    ts = event.get("timestamp")
    if ts is None:
        return datetime.min

    if isinstance(ts, str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    if isinstance(ts, datetime):
        return ts

    return datetime.min


def get_aggregated_activity(
    project_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    event_types: list[str] | None = None,
) -> tuple[list[ActivityEvent], int]:
    """Get aggregated activity from all sources, sorted by timestamp.

    Args:
        project_id: Filter by project (None for all)
        limit: Max events per page
        offset: Pagination offset
        event_types: Filter by event types (task, backup, git)

    Returns:
        Tuple of (events, total_count_estimate)
    """
    types_to_fetch = event_types or ["task", "backup", "git"]

    # Fetch more than needed to account for merging/sorting
    fetch_limit = limit + offset + 20

    all_events: list[ActivityEvent] = []

    if "task" in types_to_fetch:
        all_events.extend(get_recent_task_events(project_id, fetch_limit))

    if "backup" in types_to_fetch:
        all_events.extend(get_recent_backup_events(project_id, fetch_limit))

    if "git" in types_to_fetch:
        all_events.extend(get_recent_git_events(project_id, fetch_limit))

    # Sort all events by timestamp (descending)
    all_events.sort(key=_parse_event_timestamp, reverse=True)

    total_estimate = len(all_events)

    # Apply pagination
    paginated = all_events[offset : offset + limit]

    return paginated, total_estimate
