"""Execution-related operations for SummitFlow Tasks API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import httpx


def start_execution(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    agent_type: str = "claude",
    use_worktree: bool = False,
) -> dict[str, Any]:
    """Start execution of a task."""
    data = {"agent_type": agent_type, "use_worktree": use_worktree}
    response = client.post(url_fn(f"/tasks/{task_id}/execute/start"), json=data)
    return cast(dict[str, Any], handle_response(response))


def get_autonomous_settings(client: httpx.Client, url_fn: Any, handle_response: Any) -> dict[str, Any]:
    """Get autonomous execution settings."""
    response = client.get(url_fn("/autonomous/settings"))
    return cast(dict[str, Any], handle_response(response))


def update_autonomous_settings(client: httpx.Client, url_fn: Any, handle_response: Any, **updates: Any) -> dict[str, Any]:
    """Update autonomous execution settings."""
    response = client.patch(url_fn("/autonomous/settings"), json=updates)
    return cast(dict[str, Any], handle_response(response))


def get_autonomous_status(client: httpx.Client, url_fn: Any, handle_response: Any) -> dict[str, Any]:
    """Get autonomous execution status and metrics."""
    response = client.get(url_fn("/autonomous/status"))
    return cast(dict[str, Any], handle_response(response))


def list_sessions(client: httpx.Client, url_fn: Any, handle_response: Any) -> list[dict[str, Any]]:
    """List agent sessions for the project."""
    response = client.get(url_fn("/sessions"))
    return cast(list[dict[str, Any]], handle_response(response))


def get_session(client: httpx.Client, url_fn: Any, handle_response: Any, session_id: str) -> dict[str, Any]:
    """Get a specific session."""
    response = client.get(url_fn(f"/sessions/{session_id}"))
    return cast(dict[str, Any], handle_response(response))


def start_autocode(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    model: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Start autocode execution for a task."""
    data: dict[str, Any] = {"dry_run": dry_run}
    if model:
        data["model"] = model
    # Autocode requests can take 10+ minutes with Claude OAuth for complex tasks
    response = client.post(
        url_fn(f"/tasks/{task_id}/autocode"),
        json=data,
        timeout=600.0,
    )
    return cast(dict[str, Any], handle_response(response))


def get_autocode_status(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    execution_id: str,
) -> dict[str, Any]:
    """Get status of an autocode execution."""
    response = client.get(url_fn(f"/tasks/{task_id}/autocode/{execution_id}"))
    return cast(dict[str, Any], handle_response(response))


def abort_autocode(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    execution_id: str,
) -> dict[str, Any]:
    """Abort a running autocode execution."""
    response = client.post(url_fn(f"/tasks/{task_id}/autocode/{execution_id}/abort"))
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
