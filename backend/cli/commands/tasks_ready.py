"""Ready tasks listing command."""

from __future__ import annotations

from ..client import APIError, STClient
from ..output import handle_api_error, output_blocked_tasks, output_task_list


def list_ready_tasks(
    limit: int,
    blocked: bool,
    client: STClient,
) -> None:
    """List tasks ready to work on (not blocked) or show blocked tasks."""
    try:
        if blocked:
            # Get pending tasks and filter to blocked ones
            result = client.list_tasks(status="pending", limit=limit * 2)
            tasks = result.get("tasks", [])

            # Filter to tasks that have blocking dependencies
            blocked_tasks = []
            blockers_map: dict[str, list[str]] = {}

            for task in tasks:
                task_id = task["id"]
                deps = client.list_dependencies(task_id)

                # Find incomplete blocking dependencies
                blocking = [
                    d
                    for d in deps
                    if d.get("dependency_type") == "blocks"
                    and d.get("depends_on_status") not in ("completed", "cancelled")
                ]

                if blocking:
                    task["blockers"] = blocking
                    blocked_tasks.append(task)

                    # Track which tasks each blocker blocks
                    for b in blocking:
                        blocker_id = b.get("depends_on_task_id", "")
                        if blocker_id not in blockers_map:
                            blockers_map[blocker_id] = []
                        blockers_map[blocker_id].append(task_id)

            blocked_tasks = blocked_tasks[:limit]
            output_blocked_tasks(blocked_tasks, blockers_map)
        else:
            result = client.list_ready(limit=limit)
            output_task_list(result["tasks"], header="READY")
    except APIError as e:
        handle_api_error(e)
        raise
