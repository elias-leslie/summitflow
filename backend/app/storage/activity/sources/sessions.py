"""Session Events Source - Fetch activity events from agent sessions."""

from __future__ import annotations

from typing import Any, cast

from ...connection import get_connection
from ..types import ActivityEvent, SessionMetadata


def get_recent_session_events(
    project_id: str | None = None,
    limit: int = 20,
) -> list[ActivityEvent]:
    """Get recent agent session events.

    Args:
        project_id: Filter by project (None for all)
        limit: Max events to return

    Returns:
        List of activity events for agent sessions
    """
    where_clause = "WHERE status IN ('completed', 'failed')"
    params: list[str | int] = []

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

    events: list[ActivityEvent] = []
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

        metadata: SessionMetadata = {
            "session_id": session_id,
            "agent_type": agent_type,
            "status": status,
            "tests_passed": tests_passed or 0,
            "tests_failed": tests_failed or 0,
        }

        events.append({
            "type": "session",
            "message": f"{agent_type.title()} session {status}{test_summary}",
            "timestamp": event_time.isoformat() if event_time else None,
            "project_id": proj_id,
            "metadata": cast(dict[str, Any], metadata),
        })
    return events
