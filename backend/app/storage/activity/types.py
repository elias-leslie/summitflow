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
    action: str


class BackupMetadata(TypedDict):
    """Metadata for backup activity events."""

    backup_id: str
    backup_type: str
    status: str
    size_bytes: int


class GitMetadata(TypedDict):
    """Metadata for git commit activity events."""

    commit_sha: str
    repo_name: str
    author_name: str
    files_changed: int
    insertions: int
    deletions: int


EventType = Literal["task", "backup", "git"]


class ActivityEvent(TypedDict):
    """A single activity event from any source."""

    type: EventType
    message: str
    timestamp: str | None
    project_id: str
    metadata: dict[str, Any]
