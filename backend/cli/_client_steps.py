"""Step operations for SummitFlow Tasks API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import httpx


def get_steps(
    client: httpx.Client, url_fn: Any, handle_response: Any, task_id: str, subtask_id: str
) -> list[dict[str, Any]]:
    """Get steps for a subtask."""
    response = client.get(url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}/steps"))
    return cast(list[dict[str, Any]], handle_response(response))


def bulk_create_steps(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    subtask_id: str,
    descriptions: list[str],
) -> dict[str, Any]:
    """Create multiple steps for a subtask in batch."""
    response = client.post(
        url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}/steps/batch"),
        json={"steps": descriptions},
    )
    return cast(dict[str, Any], handle_response(response))


def append_steps(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    subtask_id: str,
    descriptions: list[str],
) -> dict[str, Any]:
    """Append steps to a subtask, continuing from highest existing step number."""
    response = client.post(
        url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}/steps/append"),
        json={"steps": descriptions},
    )
    return cast(dict[str, Any], handle_response(response))


def update_step(
    client: httpx.Client,
    global_url_fn: Any,
    handle_response: Any,
    task_id: str,
    subtask_id: str,
    step_number: int,
    passes: bool,
) -> dict[str, Any]:
    """Update a step's passes status."""
    data = {"passes": passes}
    response = client.patch(
        global_url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}"),
        json=data,
    )
    return cast(dict[str, Any], handle_response(response))


def delete_step(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    subtask_id: str,
    step_number: int,
    force: bool = False,
) -> dict[str, Any]:
    """Delete a step from a subtask.

    Args:
        client: HTTP client
        url_fn: URL builder function
        handle_response: Response handler function
        task_id: Task ID
        subtask_id: Subtask ID
        step_number: Step number to delete
        force: If True, allow deletion of passed steps

    Returns:
        Deletion result with audit info
    """
    params = {"force": "true"} if force else {}
    response = client.delete(
        url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}"),
        params=params,
    )
    return cast(dict[str, Any], handle_response(response))


def insert_step(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    subtask_id: str,
    position: int,
    description: str,
) -> dict[str, Any]:
    """Insert a step at a specific position, shifting existing steps down."""
    response = client.post(
        url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}/steps/{position}/insert"),
        json={"description": description},
    )
    return cast(dict[str, Any], handle_response(response))


def create_step_with_verification(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    subtask_id: str,
    description: str,
    verify_command: str,
    expected_output: str,
) -> dict[str, Any]:
    """Create a single step with required verification."""
    response = client.post(
        url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}/steps"),
        json={
            "description": description,
            "verify_command": verify_command,
            "expected_output": expected_output,
        },
    )
    return cast(dict[str, Any], handle_response(response))


def update_step_fields(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    subtask_id: str,
    step_number: int,
    description: str | None = None,
) -> dict[str, Any]:
    """Update step description."""
    data: dict[str, Any] = {}
    if description is not None:
        data["description"] = description

    response = client.patch(
        url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}/fields"),
        json=data,
    )
    return cast(dict[str, Any], handle_response(response))


def update_step_status(
    client: httpx.Client,
    global_url_fn: Any,
    handle_response: Any,
    task_id: str,
    subtask_id: str,
    step_number: int,
    status: str,
    fix_step_number: int | None = None,
) -> dict[str, Any]:
    """Update step status."""
    data: dict[str, Any] = {"status": status}
    if fix_step_number is not None:
        data["fix_step_number"] = fix_step_number

    response = client.patch(
        global_url_fn(f"/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}/status"),
        json=data,
    )
    return cast(dict[str, Any], handle_response(response))
