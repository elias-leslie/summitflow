"""Activity Event Sources - Fetch events from different data sources.

This module re-exports all event source functions.
"""

from __future__ import annotations

from .git import get_recent_git_events
from .tasks import get_recent_task_events

__all__ = [
    "get_recent_git_events",
    "get_recent_task_events",
]
