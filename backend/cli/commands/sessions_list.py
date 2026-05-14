"""Session list rendering helpers."""

from __future__ import annotations

from typing import Any

from .._observability import refresh_agent_observability
from ..client import APIError, STClient
from ..config import get_project_override
from typing import Callable

from ..client import APIError
from ..config import get_project_override
from ..output import handle_api_error, is_compact

_ACTIVE_STATUS_ALIASES = {"running", "stale", "reapable"}
_LIVE_STATUS_ALIASES = {"stale", "reapable"}


def _normalize_status_filter(status_filter: str | None) -> str | None:
    if not status_filter:
        return None
    normalized = status_filter.strip().lower()
    if normalized in _ACTIVE_STATUS_ALIASES:
        return "active"
    return normalized


def _session_live_state(session: dict[str, Any]) -> str:
    live = session.get("live_activity")
    if isinstance(live, dict):
        raw = live.get("lifecycle_state") or live.get("status") or live.get("state")
        if raw:
            return str(raw)
    return str(session.get("status") or "-")


def _session_matches_status_alias(session: dict[str, Any], status_filter: str | None) -> bool:
    if not status_filter:
        return True
    normalized = status_filter.strip().lower()
    if normalized not in _LIVE_STATUS_ALIASES:
        return True
    live = session.get("live_activity")
    if not isinstance(live, dict):
        return False
    state = _session_live_state(session).strip().lower()
    if normalized == "reapable":
        return bool(live.get("reapable")) or state == "reapable"
    return bool(live.get("is_stale")) or bool(live.get("reapable")) or state in {"reapable", "stale", "stalled"}


def _session_line(session: dict[str, Any]) -> str:
    session_id = str(session.get("id") or "-")
    short_id = session_id[:8]
    project_id = str(session.get("project_id") or "-")
    status = str(session.get("status") or "-")
    agent = str(session.get("agent_slug") or "-")
    task_id = str(session.get("task_id") or "-")
    live_state = _session_live_state(session)
    updated = str(session.get("updated_at") or "-")
    return (
        f"SES {project_id} | {status} | {agent} | {short_id} | "
        f"task={task_id} state={live_state} updated={updated}"
    )


def _output_session_list_compact(sessions: list[dict[str, Any]]) -> None:
    print(f"SESSIONS[{len(sessions)}]")
    for session in sessions:
        print(_session_line(session))


def render_session_list(
    status_filter: str | None,
    limit: int,
    agent_slug: str | None,
    parent_session_id: str | None,
    project_id: str | None,
    include_unassigned: bool = True,
    *,
    client: Any,
    output_json_fn: Callable[[Any], None] | None = None,
) -> None:
    normalized_status = _normalize_status_filter(status_filter)
    resolved_project_id = project_id or get_project_override()

    try:
        sessions = client.list_sessions(
            status=normalized_status,
            limit=limit,
            page=1,
            agent_slug=agent_slug,
            parent_session_id=parent_session_id,
            project_id=resolved_project_id,
        )
    except APIError as e:
        handle_api_error(e)
        return

    sessions = [session for session in sessions if _session_matches_status_alias(session, status_filter)]
    if not include_unassigned:
        sessions = [session for session in sessions if session.get("agent_slug")]

    if is_compact():
        _output_session_list_compact(sessions)
        return
    if output_json_fn is not None:
        output_json_fn(sessions)
        return
    from ..output import output_json
    output_json(sessions)
