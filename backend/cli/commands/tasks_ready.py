"""Ready tasks listing command."""

from __future__ import annotations

from ..client import APIError, STClient
from ..output import handle_api_error, output_blocked_tasks, output_task_list


def _get_blocking_deps(deps: list[dict]) -> list[dict]:
    """Return only incomplete blocking dependencies."""
    return [
        d
        for d in deps
        if d.get("dependency_type") == "blocks"
        and d.get("depends_on_status") not in ("completed", "cancelled")
    ]


def _update_blockers_map(
    blockers_map: dict[str, list[str]],
    blocking: list[dict],
    task_id: str,
) -> None:
    """Record which tasks each blocker is blocking."""
    for b in blocking:
        blocker_id = b.get("depends_on_task_id", "")
        blockers_map.setdefault(blocker_id, []).append(task_id)


def _collect_blocked_tasks(
    tasks: list[dict],
    client: STClient,
    limit: int,
) -> tuple[list[dict], dict[str, list[str]]]:
    """Filter tasks to those with incomplete blocking dependencies."""
    blocked_tasks: list[dict] = []
    blockers_map: dict[str, list[str]] = {}

    for task in tasks:
        task_id = task["id"]
        deps = client.list_dependencies(task_id)
        blocking = _get_blocking_deps(deps)

        if not blocking:
            continue

        task["blockers"] = blocking
        blocked_tasks.append(task)
        _update_blockers_map(blockers_map, blocking, task_id)

    return blocked_tasks[:limit], blockers_map


def list_ready_tasks(
    limit: int,
    blocked: bool,
    client: STClient,
) -> None:
    """List tasks ready to work on (not blocked) or show blocked tasks."""
    try:
        if blocked:
            result = client.list_tasks(status="pending", limit=limit * 2)
            tasks = result.get("tasks", [])
            blocked_tasks, blockers_map = _collect_blocked_tasks(tasks, client, limit)
            output_blocked_tasks(blocked_tasks, blockers_map)
        else:
            result = client.list_ready(limit=limit)
            output_task_list(result["tasks"], header="READY")
    except APIError as e:
        handle_api_error(e)
        raise
