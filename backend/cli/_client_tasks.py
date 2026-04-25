"""Task CRUD operations for SummitFlow Tasks API."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Any, cast

from app.storage.tasks import canonicalize_task_id

if TYPE_CHECKING:
    import httpx


def create_task(
    client: httpx.Client, url_fn: Any, handle_response: Any, data: dict[str, Any]
) -> dict[str, Any]:
    """Create a new task."""
    response = client.post(url_fn("/tasks"), json=data)
    return cast(dict[str, Any], handle_response(response))


def batch_create_tasks(
    client: httpx.Client, url_fn: Any, handle_response: Any, items: list[dict[str, Any]]
) -> dict[str, Any]:
    """Create multiple tasks in batch."""
    response = client.post(url_fn("/tasks/batch"), json={"items": items})
    return cast(dict[str, Any], handle_response(response))


def get_task(
    client: httpx.Client, global_url_fn: Any, handle_response: Any, task_id: str
) -> dict[str, Any]:
    """Get a task by ID (global lookup)."""
    response = client.get(global_url_fn(f"/tasks/{canonicalize_task_id(task_id)}"))
    return cast(dict[str, Any], handle_response(response))


def export_task(
    client: httpx.Client, global_url_fn: Any, handle_response: Any, task_id: str
) -> dict[str, Any]:
    """Export complete task data by ID (global lookup)."""
    response = client.get(global_url_fn(f"/tasks/{canonicalize_task_id(task_id)}/export"))
    return cast(dict[str, Any], handle_response(response))


def get_task_completion_readiness(
    client: httpx.Client, global_url_fn: Any, handle_response: Any, task_id: str
) -> dict[str, Any]:
    """Get completion-readiness gates for a task."""
    response = client.get(global_url_fn(f"/tasks/{canonicalize_task_id(task_id)}/completion-readiness"))
    return cast(dict[str, Any], handle_response(response))


def get_task_logs(
    client: httpx.Client,
    global_url_fn: Any,
    handle_response: Any,
    project_id: str,
    task_id: str,
) -> dict[str, Any]:
    """Get task progress logs in JSON form."""
    response = client.get(
        global_url_fn(f"/projects/{project_id}/tasks/{canonicalize_task_id(task_id)}/logs"),
        params={"format": "json"},
    )
    return cast(dict[str, Any], handle_response(response))


def list_tasks(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    status: str | None = None,
    task_type: str | None = None,
    priority: int | None = None,
    labels: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List tasks with optional filters."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status
    if task_type:
        params["type"] = task_type
    if priority is not None:
        params["priority"] = priority
    if labels:
        params["labels"] = ",".join(labels)

    response = client.get(url_fn("/tasks"), params=params)
    return cast(dict[str, Any], handle_response(response))


def list_ready(
    client: httpx.Client, url_fn: Any, handle_response: Any, limit: int = 50
) -> dict[str, Any]:
    """List tasks ready to work on."""
    response = client.get(url_fn("/tasks/ready"), params={"limit": limit})
    return cast(dict[str, Any], handle_response(response))


def update_task(
    client: httpx.Client, url_fn: Any, handle_response: Any, task_id: str, **updates: Any
) -> dict[str, Any]:
    """Update a task."""
    response = client.patch(url_fn(f"/tasks/{canonicalize_task_id(task_id)}"), json=updates)
    return cast(dict[str, Any], handle_response(response))


def update_status(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    status: str,
    error_message: str | None = None,
    reason: str | None = None,
    skip_gates: bool = False,
) -> dict[str, Any]:
    """Update task status."""
    data: dict[str, Any] = {"status": status}
    if error_message:
        data["error_message"] = error_message
    if reason:
        data["reason"] = reason
    if skip_gates:
        data["skip_gates"] = True

    response = client.patch(url_fn(f"/tasks/{canonicalize_task_id(task_id)}/status"), json=data)
    return cast(dict[str, Any], handle_response(response))


def delete_task(
    client: httpx.Client, url_fn: Any, handle_response: Any, task_id: str
) -> dict[str, Any]:
    """Delete a task."""
    response = client.delete(url_fn(f"/tasks/{canonicalize_task_id(task_id)}"))
    return cast(dict[str, Any], handle_response(response))


def claim_task(
    client: httpx.Client,
    url_fn: Any,
    handle_response: Any,
    task_id: str,
    lock_minutes: int = 30,
    worker_id: str | None = None,
) -> dict[str, Any]:
    """Claim a task for exclusive execution."""
    if worker_id is None:
        worker_id = socket.gethostname()

    data = {"worker_id": worker_id, "lock_minutes": lock_minutes}
    response = client.post(url_fn(f"/tasks/{canonicalize_task_id(task_id)}/claim"), json=data)
    return cast(dict[str, Any], handle_response(response))


def release_task(
    client: httpx.Client, url_fn: Any, handle_response: Any, task_id: str
) -> dict[str, Any]:
    """Release a claimed task."""
    response = client.post(url_fn(f"/tasks/{canonicalize_task_id(task_id)}/release"))
    return cast(dict[str, Any], handle_response(response))


def append_log(
    client: httpx.Client, global_url_fn: Any, handle_response: Any, task_id: str, entry: str
) -> dict[str, Any]:
    """Append an entry to the task's progress log."""
    data = {"entry": entry}
    response = client.post(global_url_fn(f"/tasks/{canonicalize_task_id(task_id)}/log"), json=data)
    return cast(dict[str, Any], handle_response(response))


def validate_ready(
    client: httpx.Client, url_fn: Any, handle_response: Any, task_id: str
) -> dict[str, Any]:
    """Validate task execution readiness."""
    response = client.post(url_fn(f"/tasks/{canonicalize_task_id(task_id)}/validate-ready"))
    return cast(dict[str, Any], handle_response(response))


def execute_task(
    client: httpx.Client, url_fn: Any, handle_response: Any, task_id: str
) -> dict[str, Any]:
    """Queue task for autonomous execution and immediate dispatch."""
    response = client.post(url_fn(f"/tasks/{canonicalize_task_id(task_id)}/execute"))
    return cast(dict[str, Any], handle_response(response))


def finalize_task_merge(
    client: httpx.Client, global_url_fn: Any, handle_response: Any, task_id: str
) -> dict[str, Any]:
    """Finalize merge/cleanup for a non-active task residue lane."""
    response = client.post(global_url_fn(f"/git/tasks/{canonicalize_task_id(task_id)}/finalize"))
    return cast(dict[str, Any], handle_response(response))


def resolve_task_conflict(
    client: httpx.Client, global_url_fn: Any, handle_response: Any, task_id: str
) -> dict[str, Any]:
    """Reopen a residue task for conflict-resolution execution."""
    response = client.post(global_url_fn(f"/git/tasks/{canonicalize_task_id(task_id)}/resolve-conflict"))
    return cast(dict[str, Any], handle_response(response))


def smart_sync_project(
    client: httpx.Client, global_url_fn: Any, handle_response: Any, project_id: str
) -> dict[str, Any]:
    """Run Smart Sync for one managed project."""
    response = client.post(global_url_fn(f"/projects/{project_id}/git/smart-sync"))
    return cast(dict[str, Any], handle_response(response))
