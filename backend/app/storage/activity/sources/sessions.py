"""Session Events Source - Fetch activity events from agent sessions."""

from __future__ import annotations

from typing import Any, cast

from ...connection import get_cursor
from ..types import ActivityEvent, SessionMetadata


def _build_session_query_params(
    project_id: str | None,
) -> tuple[str, list[str | int]]:
    """Build WHERE clause and params for session query.

    Args:
        project_id: Optional project filter

    Returns:
        Tuple of (where_clause, params)
    """
    where_clause = "WHERE status IN ('completed', 'failed')"
    params: list[str | int] = []

    if project_id:
        where_clause += " AND project_id = %s"
        params.append(project_id)

    return where_clause, params


def _fetch_session_rows(
    where_clause: str,
    params: list[str | int],
    limit: int,
) -> list[Any]:
    """Execute the session query and return raw rows.

    Args:
        where_clause: SQL WHERE clause
        params: Query parameters
        limit: Max rows to return

    Returns:
        List of raw database rows
    """
    with get_cursor() as cur:
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
        return cur.fetchall()


def _row_to_event(row: Any) -> ActivityEvent:
    """Convert a raw database row to an ActivityEvent.

    Args:
        row: Raw database row tuple

    Returns:
        ActivityEvent dict
    """
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

    return {
        "type": "session",
        "message": f"{agent_type.title()} session {status}{test_summary}",
        "timestamp": event_time.isoformat() if event_time else None,
        "project_id": proj_id,
        "metadata": cast(dict[str, Any], metadata),
    }


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
    where_clause, params = _build_session_query_params(project_id)
    rows = _fetch_session_rows(where_clause, params, limit)
    return [_row_to_event(row) for row in rows]
