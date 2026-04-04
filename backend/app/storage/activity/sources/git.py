"""Git Events Source - Fetch activity events from repository commit history."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, cast

from ....utils._git_core import _resolve_project_id, get_managed_repos
from ....utils._git_diff import get_recent_commits
from ...projects import get_project_root_path
from ..types import ActivityEvent, GitMetadata


def _to_git_event(commit: Any, project_id: str) -> ActivityEvent:
    """Convert a git commit record into an activity event."""
    metadata: GitMetadata = {
        "commit_sha": commit.sha,
        "repo_name": commit.repo_name,
        "author_name": commit.author_name,
        "files_changed": commit.files_changed,
        "insertions": commit.insertions,
        "deletions": commit.deletions,
    }
    return {
        "type": "git",
        "message": f"Commit {commit.short_sha}: {commit.message}",
        "timestamp": commit.date,
        "project_id": project_id,
        "metadata": cast(dict[str, Any], metadata),
    }


def _parse_event_timestamp(event: ActivityEvent) -> datetime:
    """Parse activity timestamps for consistent cross-repo sorting."""
    timestamp = event.get("timestamp")
    if not isinstance(timestamp, str):
        return datetime.min
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def _get_project_git_events(project_id: str, limit: int) -> list[ActivityEvent]:
    """Collect recent git activity for a single project repo."""
    root_path = get_project_root_path(project_id)
    if not root_path:
        return []
    repo_path = Path(root_path)
    return [_to_git_event(commit, project_id) for commit in get_recent_commits(repo_path, limit=limit)]


def _get_managed_repo_git_events(limit: int) -> list[ActivityEvent]:
    """Collect and merge recent git activity across all managed repos."""
    events: list[ActivityEvent] = []
    for repo_path in get_managed_repos():
        project_id = _resolve_project_id(repo_path)
        if not project_id:
            continue
        for commit in get_recent_commits(repo_path, limit=limit):
            events.append(_to_git_event(commit, project_id))
    events.sort(key=_parse_event_timestamp, reverse=True)
    return events[:limit]


def get_recent_git_events(
    project_id: str | None = None,
    limit: int = 20,
) -> list[ActivityEvent]:
    """Get recent git commit events from repository history.

    Args:
        project_id: Filter by project (None for all)
        limit: Max events to return

    Returns:
        List of activity events for git commits
    """
    if project_id:
        return _get_project_git_events(project_id, limit)
    return _get_managed_repo_git_events(limit)
