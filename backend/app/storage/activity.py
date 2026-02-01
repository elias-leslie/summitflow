"""Activity Storage - Aggregated activity feed from multiple sources.

This module provides data access for the unified activity feed:
- Task completions (from tasks table)
- Agent sessions (from agent_sessions table)
- Backup events (from backups table)
- Git commits (from git data)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .connection import get_connection


def get_recent_task_events(
    project_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Get recent task completion events.

    Args:
        project_id: Filter by project (None for all)
        limit: Max events to return

    Returns:
        List of activity events for completed/closed tasks
    """
    where_clause = "WHERE status IN ('completed', 'cancelled', 'blocked')"
    params: list[Any] = []

    if project_id:
        where_clause += " AND project_id = %s"
        params.append(project_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, project_id, title, status, completed_at, created_at
            FROM tasks
            {where_clause}
            ORDER BY COALESCE(completed_at, created_at) DESC
            LIMIT %s
            """,
            [*params, limit],
        )
        rows = cur.fetchall()

    events = []
    for row in rows:
        task_id, proj_id, title, status, completed_at, created_at = row
        event_time = completed_at or created_at
        events.append(
            {
                "type": "task",
                "message": f"Task {status}: {title}",
                "timestamp": event_time.isoformat() if event_time else None,
                "project_id": proj_id,
                "metadata": {
                    "task_id": task_id,
                    "status": status,
                    "title": title,
                },
            }
        )
    return events


def get_recent_session_events(
    project_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Get recent agent session events.

    Args:
        project_id: Filter by project (None for all)
        limit: Max events to return

    Returns:
        List of activity events for agent sessions
    """
    where_clause = "WHERE status IN ('completed', 'failed')"
    params: list[Any] = []

    if project_id:
        where_clause += " AND project_id = %s"
        params.append(project_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT session_id, project_id, agent_type, status, ended_at, started_at,
                   tests_passed, tests_failed
            FROM agent_sessions
            {where_clause}
            ORDER BY COALESCE(ended_at, started_at) DESC
            LIMIT %s
            """,
            [*params, limit],
        )
        rows = cur.fetchall()

    events = []
    for row in rows:
        (
            session_id,
            proj_id,
            agent_type,
            status,
            ended_at,
            started_at,
            tests_passed,
            tests_failed,
        ) = row
        event_time = ended_at or started_at
        test_summary = ""
        if tests_passed or tests_failed:
            test_summary = f" ({tests_passed} passed, {tests_failed} failed)"
        events.append(
            {
                "type": "session",
                "message": f"{agent_type.title()} session {status}{test_summary}",
                "timestamp": event_time.isoformat() if event_time else None,
                "project_id": proj_id,
                "metadata": {
                    "session_id": session_id,
                    "agent_type": agent_type,
                    "status": status,
                    "tests_passed": tests_passed or 0,
                    "tests_failed": tests_failed or 0,
                },
            }
        )
    return events


def get_recent_backup_events(
    project_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Get recent backup events.

    Args:
        project_id: Filter by project (None for all)
        limit: Max events to return

    Returns:
        List of activity events for backups
    """
    where_clause = "WHERE status IN ('completed', 'failed')"
    params: list[Any] = []

    if project_id:
        where_clause += " AND project_id = %s"
        params.append(project_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, project_id, backup_type, status, size_bytes, completed_at, created_at
            FROM backups
            {where_clause}
            ORDER BY COALESCE(completed_at, created_at) DESC
            LIMIT %s
            """,
            [*params, limit],
        )
        rows = cur.fetchall()

    events = []
    for row in rows:
        backup_id, proj_id, backup_type, status, size_bytes, completed_at, created_at = row
        event_time = completed_at or created_at
        size_mb = f" ({size_bytes / 1024 / 1024:.1f} MB)" if size_bytes else ""
        events.append(
            {
                "type": "backup",
                "message": f"{backup_type.title()} backup {status}{size_mb}",
                "timestamp": event_time.isoformat() if event_time else None,
                "project_id": proj_id,
                "metadata": {
                    "backup_id": backup_id,
                    "backup_type": backup_type,
                    "status": status,
                    "size_bytes": size_bytes or 0,
                },
            }
        )
    return events


def get_recent_git_events(
    project_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Get recent git commit events from agent sessions.

    Git commits are tracked via agent sessions that have a git_commit_sha.

    Args:
        project_id: Filter by project (None for all)
        limit: Max events to return

    Returns:
        List of activity events for git commits
    """
    where_clause = "WHERE git_commit_sha IS NOT NULL"
    params: list[Any] = []

    if project_id:
        where_clause += " AND project_id = %s"
        params.append(project_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT project_id, git_commit_sha, notes, ended_at, agent_type
            FROM agent_sessions
            {where_clause}
            ORDER BY ended_at DESC NULLS LAST
            LIMIT %s
            """,
            [*params, limit],
        )
        rows = cur.fetchall()

    events = []
    for row in rows:
        proj_id, sha, notes, ended_at, agent_type = row
        short_sha = sha[:7] if sha else "unknown"
        commit_msg = notes[:50] + "..." if notes and len(notes) > 50 else notes or "No message"
        events.append(
            {
                "type": "git",
                "message": f"Commit {short_sha}: {commit_msg}",
                "timestamp": ended_at.isoformat() if ended_at else None,
                "project_id": proj_id,
                "metadata": {
                    "commit_sha": sha,
                    "agent_type": agent_type,
                    "notes": notes,
                },
            }
        )
    return events


def get_aggregated_activity(
    project_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    event_types: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Get aggregated activity from all sources, sorted by timestamp.

    Args:
        project_id: Filter by project (None for all)
        limit: Max events per page
        offset: Pagination offset
        event_types: Filter by event types (task, session, backup, git)

    Returns:
        Tuple of (events, total_count_estimate)
    """
    types_to_fetch = event_types or ["task", "session", "backup", "git"]

    # Fetch more than needed to account for merging/sorting
    fetch_limit = limit + offset + 20

    all_events: list[dict[str, Any]] = []

    if "task" in types_to_fetch:
        all_events.extend(get_recent_task_events(project_id, fetch_limit))

    if "session" in types_to_fetch:
        all_events.extend(get_recent_session_events(project_id, fetch_limit))

    if "backup" in types_to_fetch:
        all_events.extend(get_recent_backup_events(project_id, fetch_limit))

    if "git" in types_to_fetch:
        all_events.extend(get_recent_git_events(project_id, fetch_limit))

    # Sort all events by timestamp (descending)
    def sort_key(event: dict[str, Any]) -> datetime:
        ts = event.get("timestamp")
        if ts is None:
            return datetime.min
        if isinstance(ts, str):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if isinstance(ts, datetime):
            return ts
        return datetime.min

    all_events.sort(key=sort_key, reverse=True)

    total_estimate = len(all_events)

    # Apply pagination
    paginated = all_events[offset : offset + limit]

    return paginated, total_estimate
