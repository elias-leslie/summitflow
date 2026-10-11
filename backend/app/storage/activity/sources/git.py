"""Git Events Source - Fetch activity events from repository commit history."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from ....utils._git_core import _resolve_project_id, get_managed_repos
from ....utils._git_diff import get_recent_commits
from ...projects import get_project_root_path, testing_project_ids
from ..types import ActivityEvent, GitMetadata

GIT_ACTIVITY_WORKERS = 4
GIT_ACTIVITY_CACHE_TTL_SECONDS = 60.0
_ALL_PROJECTS_KEY = "*"

# key -> (monotonic fetched_at, limit fetched, events); shared across requests
_git_events_cache: dict[str, tuple[float, int, list[ActivityEvent]]] = {}
_git_events_cache_lock = threading.Lock()


def clear_git_events_cache() -> None:
    with _git_events_cache_lock:
        _git_events_cache.clear()


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


def _collect_repo_git_events(
    repo_and_project: tuple[Path, str],
    limit: int,
) -> list[ActivityEvent]:
    """Collect one repository's events for bounded parallel aggregation."""
    repo_path, project_id = repo_and_project
    return [
        _to_git_event(commit, project_id)
        for commit in get_recent_commits(repo_path, limit=limit)
    ]


def _get_managed_repo_git_events(limit: int) -> list[ActivityEvent]:
    """Collect and merge recent git activity across all managed repos."""
    testing = testing_project_ids()
    repos = [
        (repo_path, project_id)
        for repo_path in get_managed_repos()
        if (project_id := _resolve_project_id(repo_path)) and project_id not in testing
    ]
    events: list[ActivityEvent] = []
    if repos:
        workers = min(GIT_ACTIVITY_WORKERS, len(repos))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for repo_events in executor.map(
                _collect_repo_git_events,
                repos,
                [limit] * len(repos),
            ):
                events.extend(repo_events)
    events.sort(key=_parse_event_timestamp, reverse=True)
    return events[:limit]


def get_recent_git_events(
    project_id: str | None = None,
    limit: int = 20,
) -> list[ActivityEvent]:
    """Get recent git commit events, reusing a scan younger than the cache TTL.

    Scanning every managed repo costs seconds, so results are cached per
    project (or for all projects) and served while fresh and deep enough.
    """
    key = project_id or _ALL_PROJECTS_KEY
    now = time.monotonic()
    with _git_events_cache_lock:
        cached = _git_events_cache.get(key)
    if cached and now - cached[0] < GIT_ACTIVITY_CACHE_TTL_SECONDS and cached[1] >= limit:
        return list(cached[2][:limit])
    events = _get_project_git_events(project_id, limit) if project_id else _get_managed_repo_git_events(limit)
    with _git_events_cache_lock:
        _git_events_cache[key] = (time.monotonic(), limit, events)
    return list(events)
