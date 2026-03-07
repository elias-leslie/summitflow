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
    mode = "A" if task.get("execution_mode") == "autonomous" else "M"
    return f"  {prefix} {task_id} P{priority} {task_type:8} [{mode}] {title}"


def _lane_task_id(session: dict[str, Any]) -> str | None:
    external_id = session.get("external_id")
    if isinstance(external_id, str) and external_id.startswith("task-"):
        return external_id
    branch = session.get("current_branch")
    if not isinstance(branch, str) or not branch:
        return None
    branch_prefix = branch.split("/", 1)[0]
    return branch_prefix if branch_prefix.startswith("task-") else None


def _fetch_live_lane_task_ids(client: STClient, project_id: str) -> set[str]:
    try:
        sessions = client.list_sessions(status="active", project_id=project_id, limit=100, page=1)
    except APIError:
        return set()
    return {
        task_id
        for session in sessions
        if (task_id := _lane_task_id(session))
    }


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
        active_tasks: list[dict[str, Any]] = []
        stale_tasks: list[dict[str, Any]] = []
        ready_count = 0
        blocked_count = 0
        active_count = 0
        stale_count = 0
        live_lane_task_ids = _fetch_live_lane_task_ids(client, pid)

        try:
            ready_resp = client.get(
                f"{client.base_url}/projects/{pid}/tasks/ready"
                f"?limit={limit_per_project}"
            )
            ready_tasks = ready_resp.get("tasks", [])
            ready_count = ready_resp.get("total", len(ready_tasks))
        except APIError:
            pass

        # Query tasks with status='blocked' (the actual blocked status)
        try:
            blocked_resp = client.get(
                f"{client.base_url}/projects/{pid}/tasks"
                f"?status=blocked&limit={limit_per_project}"
            )
            blocked_tasks = blocked_resp.get("tasks", [])
            blocked_count = blocked_resp.get("total", len(blocked_tasks))
        except APIError:
            pass

        # Also check for pending tasks with blocking dependencies
        try:
            dep_blocked_resp = client.get(
                f"{client.base_url}/projects/{pid}/tasks/blocked"
                f"?limit={limit_per_project}"
            )
            dep_blocked = dep_blocked_resp.get("tasks", [])
            # Merge, avoiding duplicates
            seen_ids = {t.get("id") for t in blocked_tasks}
            for t in dep_blocked:
                if t.get("id") not in seen_ids:
                    blocked_tasks.append(t)
                    blocked_count += 1
        except APIError:
            pass

        # Check for active tasks (running/queue)
        for active_status in ("running", "queue"):
            try:
                active_resp = client.get(
                    f"{client.base_url}/projects/{pid}/tasks"
                    f"?status={active_status}&limit=100"
                )
                active_batch = active_resp.get("tasks", [])
                if active_status == "queue":
                    active_tasks.extend(active_batch)
                    active_count += active_resp.get("total", len(active_batch))
                    continue
                for task in active_batch:
                    if task.get("id") in live_lane_task_ids:
                        active_tasks.append(task)
                    else:
                        stale_tasks.append(task)
                active_count += len([task for task in active_batch if task.get("id") in live_lane_task_ids])
                stale_count += len([task for task in active_batch if task.get("id") not in live_lane_task_ids])
            except APIError:
                pass

        total_ready += ready_count
        total_blocked += blocked_count

        results.append({
            "project_id": pid,
            "project_name": pname,
            "ready_tasks": sorted(ready_tasks, key=_task_sort_key),
            "ready_count": ready_count,
            "blocked_tasks": sorted(blocked_tasks, key=_task_sort_key),
            "blocked_count": blocked_count,
            "active_tasks": active_tasks,
            "active_count": active_count,
            "stale_tasks": stale_tasks,
            "stale_count": stale_count,
        })

    # Sort projects: those with blocked/active/ready tasks first
    total_active = sum(r["active_count"] for r in results)
    total_stale = sum(r["stale_count"] for r in results)
    results.sort(
        key=lambda r: (-(r["blocked_count"]), -(r["stale_count"]), -(r["active_count"]), -(r["ready_count"]))
    )

    # Output
    project_count = len(results)
    print(
        f"READY-ALL[{total_ready} ready, {total_blocked} blocked, "
        f"{total_active} active, {total_stale} stale across {project_count} projects]"
    )

    for r in results:
        pid = r["project_id"]
        parts = [f"{r['ready_count']} ready"]
        if r["blocked_count"]:
            parts.append(f"{r['blocked_count']} blocked")
        if r["active_count"]:
            parts.append(f"{r['active_count']} active")
        if r["stale_count"]:
            parts.append(f"{r['stale_count']} stale")
        label = ", ".join(parts)
        print(f"\n{pid} ({label})")

        # Show active tasks (currently running)
        for task in r["active_tasks"][:limit_per_project]:
            status = task.get("status", "running")
            print(_format_task_line(task, prefix="~") + f" [{status}]")

        for task in r["stale_tasks"][:limit_per_project]:
            print(_format_task_line(task, prefix="?") + " [stale-running]")

        # Show blocked tasks (need attention)
        for task in r["blocked_tasks"][:limit_per_project]:
            print(_format_task_line(task, prefix="!"))

        # Show ready tasks (bugs first, then by priority)
        for task in r["ready_tasks"][:limit_per_project]:
            prefix = "*" if task.get("task_type") == "bug" else " "
            print(_format_task_line(task, prefix=prefix))

        if not r["blocked_tasks"] and not r["ready_tasks"] and not r["active_tasks"]:
            print("  (no pending tasks)")

    # Footer
    print(f"\nTOTAL: {total_ready} ready | {total_blocked} blocked | {total_active} active | {total_stale} stale")
