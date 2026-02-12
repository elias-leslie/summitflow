"""Activity Storage - Compatibility shim.

This file maintains backward compatibility by re-exporting from the activity package.
The actual implementation has been refactored into a package structure.
"""

from __future__ import annotations

from .activity import (
    ActivityEvent,
    EventType,
    get_aggregated_activity,
    get_recent_backup_events,
    get_recent_git_events,
    get_recent_session_events,
    get_recent_task_events,
)

__all__ = [
    "ActivityEvent",
    "EventType",
    "get_aggregated_activity",
    "get_recent_backup_events",
    "get_recent_git_events",
    "get_recent_session_events",
    "get_recent_task_events",
]
