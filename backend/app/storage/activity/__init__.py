"""Activity Storage - Aggregated activity feed from multiple sources.

This module provides data access for the unified activity feed:
- Task completions (from tasks table)
- Agent sessions (from agent_sessions table)
- Backup events (from backups table)
- Git commits (from git data)

All public functions maintain the same API for backward compatibility.
"""

from __future__ import annotations

from .aggregator import get_aggregated_activity
from .sources import (
    get_recent_backup_events,
    get_recent_git_events,
    get_recent_session_events,
    get_recent_task_events,
)
from .types import ActivityEvent, EventType

__all__ = [
    "ActivityEvent",
    "EventType",
    "get_aggregated_activity",
    "get_recent_backup_events",
    "get_recent_git_events",
    "get_recent_session_events",
    "get_recent_task_events",
]
