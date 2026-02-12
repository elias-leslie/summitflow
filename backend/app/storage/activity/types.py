"""Activity Storage Types - Type definitions for activity events.

This module provides TypedDict definitions for activity events from different sources.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class TaskMetadata(TypedDict):
    """Metadata for task activity events."""

    task_id: str
    status: str
    title: str


class SessionMetadata(TypedDict):
    """Metadata for session activity events."""

    session_id: str
    agent_type: str
    status: str
    tests_passed: int
    tests_failed: int


class BackupMetadata(TypedDict):
    """Metadata for backup activity events."""

    backup_id: str
    backup_type: str
    status: str
    size_bytes: int


class GitMetadata(TypedDict):
    """Metadata for git commit activity events."""

    commit_sha: str
    agent_type: str
    notes: str | None


EventType = Literal["task", "session", "backup", "git"]


class ActivityEvent(TypedDict):
    """A single activity event from any source."""

    type: EventType
    message: str
    timestamp: str | None
    project_id: str
    metadata: dict[str, Any]
