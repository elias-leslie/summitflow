"""Cross-project ready tasks summary command."""

from __future__ import annotations

from typing import Any

from .._output_formatters import truncate
from ..client import APIError, STClient


def _task_sort_key(task: dict[str, Any]) -> tuple[int, int, str]:
    """Sort key: bugs first, then by priority (lower = higher), then title."""
    task_type = task.get("task_type", "task")
    type_order = 0 if task_type == "bug" else 1 if task_type == "feature" else 2
    priority = task.get("priority", 3)
    title = task.get("title", "")
    return (type_order, priority, title)


def _format_task_line(task: dict[str, Any], prefix: str = " ") -> str:
    """Format a single task line for ready-all output."""
    priority = task.get("priority", 3)
    task_type = (task.get("task_type") or "task")[:8]
    title = truncate(task.get("title") or "", 55)
    task_id = task.get("id", "?")
    return f"  {prefix} {task_id} P{priority} {task_type:8} {title}"


def list_ready_all(
    limit_per_project: int,
    client: STClient,
) -> None:
    """List ready and blocked tasks across all projects."""
    # Fetch all projects
    try:
        projects_resp = client.get(client._global_url("/projects"))
    except APIError as e:
        print(f"ERR: Failed to list projects: {e}")
        return

    projects: list[dict[str, Any]] = (
        projects_resp if isinstance(projects_resp, list) else projects_resp.get("projects", [])
    )

    if not projects:
        print("No projects found")
        return

    # Collect data for each project
    results: list[dict[str, Any]] = []
    total_ready = 0
    total_blocked = 0

    for project in projects:
        pid = project.get("id") or project.get("project_id", "")
        pname = project.get("name", pid)

        ready_tasks: list[dict[str, Any]] = []
        blocked_tasks: list[dict[str, Any]] = []
        ready_count = 0
        blocked_count = 0

        try:
            ready_resp = client.get(
                f"{client.base_url}/projects/{pid}/tasks/ready"
                f"?limit={limit_per_project}"
            )
            ready_tasks = ready_resp.get("tasks", [])
            ready_count = ready_resp.get("total", len(ready_tasks))
        except APIError:
            pass

        try:
            blocked_resp = client.get(
                f"{client.base_url}/projects/{pid}/tasks/blocked"
                f"?limit={limit_per_project}"
            )
            blocked_tasks = blocked_resp.get("tasks", [])
            blocked_count = blocked_resp.get("total", len(blocked_tasks))
        except APIError:
            pass

        total_ready += ready_count
        total_blocked += blocked_count

        results.append({
            "project_id": pid,
            "project_name": pname,
            "ready_tasks": sorted(ready_tasks, key=_task_sort_key),
            "ready_count": ready_count,
            "blocked_tasks": blocked_tasks,
            "blocked_count": blocked_count,
        })

    # Sort projects: those with blocked/ready tasks first
    results.sort(key=lambda r: (-(r["blocked_count"]), -(r["ready_count"])))

    # Output
    project_count = len(results)
    print(f"READY-ALL[{total_ready} ready, {total_blocked} blocked across {project_count} projects]")

    for r in results:
        pid = r["project_id"]
        parts = [f"{r['ready_count']} ready"]
        if r["blocked_count"]:
            parts.append(f"{r['blocked_count']} blocked")
        label = ", ".join(parts)
        print(f"\n{pid} ({label})")

        # Show blocked tasks first (most urgent)
        for task in r["blocked_tasks"][:limit_per_project]:
            blockers = task.get("blockers", [])
            blocker_ids = ", ".join(
                b.get("depends_on_task_id", "?")[:8] for b in blockers[:2]
            )
            suffix = f" (blocked by: {blocker_ids})" if blocker_ids else ""
            print(_format_task_line(task, prefix="!") + suffix)

        # Show ready tasks (bugs first, then by priority)
        for task in r["ready_tasks"][:limit_per_project]:
            prefix = "*" if task.get("task_type") == "bug" else " "
            print(_format_task_line(task, prefix=prefix))

        if not r["blocked_tasks"] and not r["ready_tasks"]:
            print("  (no pending tasks)")

    # Footer
    print(f"\nTOTAL: {total_ready} ready | {total_blocked} blocked")
