"""Subtask operations for SummitFlow Tasks API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import httpx


def get_subtasks(
    client: httpx.Client,
    global_url_fn: Any,
    handle_response: Any,
    task_id: str,
    include_steps: bool = False,
) -> dict[str, Any]:
    """Get subtasks for a task."""
    params = {"include_steps": str(include_steps).lower()}
    response = client.get(global_url_fn(f"/tasks/{task_id}/subtasks"), params=params)
    return cast(dict[str, Any], handle_response(response))


def create_subtask(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    subtask_id: str,
    description: str,
    phase: str = "implementation",
    steps: list[str | dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
    subtask_type: str | None = None,
) -> dict[str, Any]:
    """Create a subtask for a task."""
    data: dict[str, Any] = {
        "subtask_id": subtask_id,
        "description": description,
        "phase": phase,
    }
    if steps:
        data["steps"] = steps
    if details:
        data["details"] = details
    if subtask_type:
        data["subtask_type"] = subtask_type
    response = client.post(url_fn(f"/tasks/{task_id}/subtasks"), json=data)
    return cast(dict[str, Any], handle_response(response))


def bulk_create_subtasks(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    subtasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create multiple subtasks for a task in batch."""
    response = client.post(
        url_fn(f"/tasks/{task_id}/subtasks/batch"),
        json={"subtasks": subtasks},
    )
    return cast(dict[str, Any], handle_response(response))


def update_subtask(
    client: httpx.Client,
    global_url_fn: Any,
    handle_response: Any,
    task_id: str,
    subtask_id: str,
    passes: bool,
) -> dict[str, Any]:
    """Update a subtask's passes status."""
    data = {"passes": passes}
    response = client.patch(global_url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}"), json=data)
    return cast(dict[str, Any], handle_response(response))


def delete_subtask(
    client: httpx.Client, url_fn: Any, handle_response: Any, task_id: str, subtask_id: str
) -> dict[str, Any]:
    """Delete a subtask and all its steps."""
    response = client.delete(url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}"))
    return cast(dict[str, Any], handle_response(response))


def log_citations(
    client: httpx.Client,
    global_url_fn: Any,
    handle_response: Any,
    task_id: str,
    subtask_id: str,
    citations: list[str],
) -> dict[str, Any]:
    """Log episode citations for a subtask."""
    response = client.post(
        global_url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}/citations"),
        json={"citations": citations},
    )
    return cast(dict[str, Any], handle_response(response))


def acknowledge_no_citations(
    client: httpx.Client, global_url_fn: Any, handle_response: Any, task_id: str, subtask_id: str
) -> dict[str, Any]:
    """Acknowledge that no memories were needed for a subtask."""
    response = client.post(
        global_url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}/citations/acknowledge-none"),
        json={"honestly_none": True},
    )
    return cast(dict[str, Any], handle_response(response))
