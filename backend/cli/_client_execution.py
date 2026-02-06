"""Execution-related operations for SummitFlow Tasks API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

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


def get_autonomous_status(
    client: httpx.Client, url_fn: Any, handle_response: Any
) -> dict[str, Any]:
    """Get autonomous execution status and metrics."""
    response = client.get(url_fn("/autonomous/status"))
    return cast(dict[str, Any], handle_response(response))


def list_sessions(client: httpx.Client, url_fn: Any, handle_response: Any) -> list[dict[str, Any]]:
    """List agent sessions for the project."""
    response = client.get(url_fn("/sessions"))
    return cast(list[dict[str, Any]], handle_response(response))


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
) -> dict[str, Any]:
    """Get Agent Hub session events linked to a task."""
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if event_type:
        params["event_type"] = event_type
    if turn is not None:
        params["turn"] = turn
    response = client.get(
        f"{base_url}/projects/{project_id}/tasks/{task_id}/agent-events",
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
    params: dict[str, Any] = {"trace_id": task_id, "limit": limit}
    if not include_debug:
        params["visibility"] = "user"
    response = client.get(
        f"{base_url}/projects/{project_id}/events",
        params=params,
    )
    return cast(dict[str, Any], handle_response(response))
