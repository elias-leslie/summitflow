"""Execution-related operations for SummitFlow Tasks API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from app.storage.tasks import canonicalize_task_id

if TYPE_CHECKING:
    import httpx


def get_autonomous_settings(
    client: httpx.Client, url_fn: Any, handle_response: Any
) -> dict[str, Any]:
    """Get autonomous execution settings."""
    response = client.get(url_fn("/autonomous/settings"))
    return cast(dict[str, Any], handle_response(response))


def update_autonomous_settings(
    client: httpx.Client, url_fn: Any, handle_response: Any, **updates: Any
) -> dict[str, Any]:
    """Update autonomous execution settings."""
    response = client.patch(url_fn("/autonomous/settings"), json=updates)
    return cast(dict[str, Any], handle_response(response))


def list_autonomous_schedules(
    client: httpx.Client, url_fn: Any, handle_response: Any
) -> list[dict[str, Any]]:
    """List autonomous schedule states."""
    response = client.get(url_fn("/autonomous/schedules"))
    return cast(list[dict[str, Any]], handle_response(response))


def update_autonomous_schedule(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    schedule_id: str,
    *,
    enabled: bool,
) -> dict[str, Any]:
    """Update one autonomous schedule state."""
    response = client.patch(url_fn(f"/autonomous/schedules/{schedule_id}"), json={"enabled": enabled})
    return cast(dict[str, Any], handle_response(response))


def run_routine_upkeep(
    client: httpx.Client, url_fn: Any, handle_response: Any
) -> dict[str, Any]:
    """Run one routine upkeep discovery cycle."""
    response = client.post(url_fn("/autonomous/upkeep/run"))
    return cast(dict[str, Any], handle_response(response))


def list_sessions(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    *,
    status: str | None = None,
    limit: int = 20,
    page: int = 1,
    agent_slug: str | None = None,
    parent_session_id: str | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """List agent sessions for the project."""
    params: dict[str, Any] = {
        "page": page,
        "page_size": limit,
    }
    if status:
        params["status"] = status
    if agent_slug:
        params["agent_slug"] = agent_slug
    if parent_session_id:
        params["parent_session_id"] = parent_session_id
    if project_id:
        params["project_id"] = project_id

    response = client.get(url_fn("/sessions"), params=params)
    data = handle_response(response)
    if isinstance(data, list):
        return cast(list[dict[str, Any]], data)
    if isinstance(data, dict):
        return cast(list[dict[str, Any]], data.get("sessions", []))
    return []


def get_session(
    client: httpx.Client, url_fn: Any, handle_response: Any, session_id: str
) -> dict[str, Any]:
    """Get a specific session."""
    response = client.get(url_fn(f"/sessions/{session_id}"))
    return cast(dict[str, Any], handle_response(response))


def get_task_agent_events(
    client: httpx.Client,
    base_url: str,
    handle_response: Any,
    project_id: str,
    task_id: str,
    event_type: str | None = None,
    turn: int | None = None,
    page: int = 1,
    page_size: int = 500,
    include_history: bool = False,
) -> dict[str, Any]:
    """Get Agent Hub session events linked to a task."""
    canonical_task_id = canonicalize_task_id(task_id)
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if event_type:
        params["event_type"] = event_type
    if turn is not None:
        params["turn"] = turn
    if include_history:
        params["include_history"] = "true"
    response = client.get(
        f"{base_url}/projects/{project_id}/tasks/{canonical_task_id}/agent-events",
        params=params,
    )
    return cast(dict[str, Any], handle_response(response))


def get_task_agent_sessions(
    client: httpx.Client,
    base_url: str,
    handle_response: Any,
    project_id: str,
    task_id: str,
    include_history: bool = False,
) -> dict[str, Any]:
    """Get Agent Hub sessions linked to a task."""
    params: dict[str, Any] = {}
    if include_history:
        params["include_history"] = "true"
    response = client.get(
        f"{base_url}/projects/{project_id}/tasks/{canonicalize_task_id(task_id)}/agent-sessions",
        params=params,
    )
    return cast(dict[str, Any], handle_response(response))


def get_events(
    client: httpx.Client,
    base_url: str,
    handle_response: Any,
    project_id: str,
    task_id: str,
    limit: int = 50,
    include_debug: bool = False,
) -> dict[str, Any]:
    """Get execution events for a task."""
    params: dict[str, Any] = {"trace_id": canonicalize_task_id(task_id), "limit": limit}
    if not include_debug:
        params["visibility"] = "user"
    response = client.get(
        f"{base_url}/projects/{project_id}/events",
        params=params,
    )
    return cast(dict[str, Any], handle_response(response))
