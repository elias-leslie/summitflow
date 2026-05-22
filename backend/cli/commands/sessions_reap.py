"""Session reap (bulk-close) helpers for the sessions CLI commands."""

from __future__ import annotations

from typing import Any, cast

from .._observability import refresh_agent_observability
from ..client import APIError, STClient


def list_all_active_sessions(
    client: STClient,
    *,
    project_id: str | None,
    page_size: int = 100,
) -> list[dict[str, object]]:
    """Fetch all active sessions via pagination and return the combined list."""
    refresh_agent_observability()
    sessions: list[dict[str, object]] = []
    page = 1
    while True:
        batch = client.list_sessions(
            status="active",
            limit=page_size,
            page=page,
            project_id=project_id,
        )
        if not batch:
            break
        sessions.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
    return sessions


def reapable_sessions(sessions: list[dict[str, object]]) -> list[dict[str, object]]:
    """Filter sessions to only those marked reapable by Agent Hub lifecycle state."""
    result: list[dict[str, object]] = []
    for session in sessions:
        live = session.get("live_activity")
        if not isinstance(live, dict):
            continue
        live_dict = cast(dict[str, Any], live)
        if bool(live_dict.get("reapable")) or live_dict.get("lifecycle_state") == "reapable":
            result.append(session)
    return result


def reapable_session_payload(session: dict[str, object]) -> dict[str, object]:
    """Extract the summary payload for one reapable session."""
    live = session.get("live_activity")
    return {
        "id": session.get("id"),
        "project_id": session.get("project_id"),
        "agent_slug": session.get("agent_slug"),
        "session_type": session.get("session_type"),
        "reapable_reason": (
            cast(dict[str, Any], live).get("reapable_reason") if isinstance(live, dict) else None
        ),
    }




def close_reapable_sessions(
    client: STClient,
    candidates: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Attempt to close each candidate session; return (closed, failed) lists."""
    closed: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    for session in candidates:
        session_id = session.get("id")
        if not isinstance(session_id, str) or not session_id:
            continue
        try:
            closed.append(client.close_session(session_id))
        except APIError as e:
            failed.append({"id": session_id, "error": str(e.detail)})
    return closed, failed
