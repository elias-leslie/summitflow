"""Git Events Source - Fetch activity events for git commits."""

from __future__ import annotations

from typing import Any, cast

from ...connection import get_connection
from ..types import ActivityEvent, GitMetadata


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
    where_clause = "WHERE git_commit_sha IS NOT NULL"
    params: list[str | int] = []

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

    events: list[ActivityEvent] = []
    for row in rows:
        proj_id, sha, notes, ended_at, agent_type = row
        short_sha = sha[:7] if sha else "unknown"
        commit_msg = notes[:50] + "..." if notes and len(notes) > 50 else notes or "No message"

        metadata: GitMetadata = {
            "commit_sha": sha,
            "agent_type": agent_type,
            "notes": notes,
        }

        events.append({
            "type": "git",
            "message": f"Commit {short_sha}: {commit_msg}",
            "timestamp": ended_at.isoformat() if ended_at else None,
            "project_id": proj_id,
            "metadata": cast(dict[str, Any], metadata),
        })
    return events
