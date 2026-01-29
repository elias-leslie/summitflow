"""Dependency operations for SummitFlow Tasks API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import httpx


def add_dependency(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    depends_on: str,
    dep_type: str = "blocks",
) -> dict[str, Any]:
    """Add a dependency to a task."""
    data = {"depends_on_task_id": depends_on, "dependency_type": dep_type}
    response = client.post(url_fn(f"/tasks/{task_id}/dependencies"), json=data)
    return cast(dict[str, Any], handle_response(response))


def list_dependencies(client: httpx.Client, global_url_fn: Any, handle_response: Any, task_id: str) -> list[dict[str, Any]]:
    """List dependencies for a task."""
    response = client.get(global_url_fn(f"/tasks/{task_id}/dependencies"))
    return cast(list[dict[str, Any]], handle_response(response))


def remove_dependency(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    depends_on: str,
    dep_type: str | None = None,
) -> dict[str, Any]:
    """Remove a dependency from a task."""
    url = f"/tasks/{task_id}/dependencies/{depends_on}"
    params = {}
    if dep_type:
        params["dependency_type"] = dep_type
    response = client.delete(url_fn(url), params=params)
    return cast(dict[str, Any], handle_response(response))
