"""Git Events Source - Fetch activity events for git commits."""

from __future__ import annotations

from typing import Any, cast

from ...connection import get_connection
from ..types import ActivityEvent, GitMetadata


def _build_git_query_params(
    project_id: str | None,
) -> tuple[str, list[str | int]]:
    """Build WHERE clause and params for git event query."""
    where_clause = "WHERE git_commit_sha IS NOT NULL"
    params: list[str | int] = []
    if project_id:
        where_clause += " AND project_id = %s"
        params.append(project_id)
    return where_clause, params


def _fetch_git_rows(
    where_clause: str,
    params: list[str | int],
    limit: int,
) -> list[tuple[Any, ...]]:
    """Execute git event query and return raw rows."""
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
        return cur.fetchall()  # type: ignore[no-any-return]


def _row_to_git_event(row: tuple[Any, ...]) -> ActivityEvent:
    """Convert a database row to a git ActivityEvent."""
    proj_id, sha, notes, ended_at, agent_type = row
    short_sha = sha[:7] if sha else "unknown"
    commit_msg = notes[:50] + "..." if notes and len(notes) > 50 else notes or "No message"
    metadata: GitMetadata = {
        "commit_sha": sha,
        "agent_type": agent_type,
        "notes": notes,
    }
    return {
        "type": "git",
        "message": f"Commit {short_sha}: {commit_msg}",
        "timestamp": ended_at.isoformat() if ended_at else None,
        "project_id": proj_id,
        "metadata": cast(dict[str, Any], metadata),
    }


def get_recent_git_events(
    project_id: str | None = None,
    limit: int = 20,
) -> list[ActivityEvent]:
    """Get recent git commit events from agent sessions.

    Git commits are tracked via agent sessions that have a git_commit_sha.

    Args:
        project_id: Filter by project (None for all)
        limit: Max events to return

    Returns:
        List of activity events for git commits
    """
    where_clause, params = _build_git_query_params(project_id)
    rows = _fetch_git_rows(where_clause, params, limit)
    return [_row_to_git_event(row) for row in rows]
