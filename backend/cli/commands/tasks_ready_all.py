"""Cross-project ready tasks summary command."""

from __future__ import annotations

from typing import Any, Protocol

from app.services.ready_task_ranking import ready_task_sort_key

from .._output_formatters import truncate
from ..client import APIError
from ..lib.checkpoint import get_snapshot_info


class ReadyAllClient(Protocol):
    base_url: str

    def _global_url(self, path: str) -> str: ...

    def get(self, url: str) -> Any: ...

    def list_sessions(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        limit: int = 20,
        page: int = 1,
        agent_slug: str | None = None,
        parent_session_id: str | None = None,
    ) -> list[dict[str, object]]: ...


def task_sort_key(task: dict[str, Any]) -> tuple[int, int, int, int, str, str]:
    """Sort key matching autonomous ready pickup order."""
    return ready_task_sort_key(task)


def _format_task_line(task: dict[str, Any], prefix: str = " ") -> str:
    """Format a single task line for ready-all output."""
    priority = task.get("priority", 3)
    task_type = (task.get("task_type") or "task")[:8]
    title = truncate(task.get("title") or "", 55)
    task_id = task.get("id", "?")
    mode = "A" if task.get("execution_mode") == "autonomous" else "M"
    return f"  {prefix} {task_id} P{priority} {task_type:8} [{mode}] {title}"


def lane_task_id(session: dict[str, Any]) -> str | None:
    external_id = session.get("external_id")
    if isinstance(external_id, str) and external_id.startswith("task-"):
        return external_id
    branch = session.get("current_branch")
    if not isinstance(branch, str) or not branch:
        return None
    branch_prefix = branch.split("/", 1)[0]
    return branch_prefix if branch_prefix.startswith("task-") else None


def _fetch_live_lane_task_ids(client: ReadyAllClient, project_id: str) -> set[str]:
    try:
        sessions = client.list_sessions(status="active", project_id=project_id, limit=100, page=1)
    except APIError:
        return set()
    return {
        task_id
        for session in sessions
        if (task_id := lane_task_id(session))
    }


def _task_has_checkpoint(task_id: str | None, project_id: str) -> bool:
    if not isinstance(task_id, str) or not task_id:
        return False
    info = get_snapshot_info(task_id)
    return bool(info and str(info.get("project_id") or "") == project_id)


def _fetch_ready_tasks(client: ReadyAllClient, pid: str) -> tuple[list[dict[str, Any]], int]:
    """Fetch ready tasks for a project, returning (tasks, total_count)."""
    try:
        resp = client.get(f"{client.base_url}/projects/{pid}/tasks/ready?limit=100")
        tasks = resp.get("tasks", [])
        return tasks, resp.get("total", len(tasks))
    except APIError:
        return [], 0


def _fetch_blocked_tasks(
    client: ReadyAllClient, pid: str, limit: int
) -> tuple[list[dict[str, Any]], int]:
    """Fetch blocked tasks (status=blocked + dep-blocked) for a project."""
    tasks: list[dict[str, Any]] = []
    count = 0
    try:
        resp = client.get(f"{client.base_url}/projects/{pid}/tasks?status=blocked&limit={limit}")
        tasks = resp.get("tasks", [])
        count = resp.get("total", len(tasks))
    except APIError:
        pass

    try:
        dep_resp = client.get(f"{client.base_url}/projects/{pid}/tasks/blocked?limit={limit}")
        seen_ids = {t.get("id") for t in tasks}
        for t in dep_resp.get("tasks", []):
            if t.get("id") not in seen_ids:
                tasks.append(t)
                count += 1
    except APIError:
        pass

    return tasks, count


def _fetch_active_stale(
    client: ReadyAllClient,
    pid: str,
    live_lane_task_ids: set[str],
    limit: int,
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]], int]:
    """Fetch running/queued tasks; split running into active (live lane) vs stale."""
    active: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    active_count = 0
    stale_count = 0

    for status in ("running", "pending"):
        try:
            resp = client.get(f"{client.base_url}/projects/{pid}/tasks?status={status}&limit=100")
            batch = resp.get("tasks", [])
        except APIError:
            continue

        if status == "pending":
            live_pending = [
                task
                for task in batch
                if task.get("id") in live_lane_task_ids
                or _task_has_checkpoint(task.get("id"), pid)
            ]
            active.extend(live_pending)
            active_count += len(live_pending)
            continue

        for task in batch:
            if task.get("id") in live_lane_task_ids or _task_has_checkpoint(task.get("id"), pid):
                active.append(task)
                active_count += 1
            else:
                stale.append(task)
                stale_count += 1

    return active, active_count, stale, stale_count


def _collect_project_data(
    client: ReadyAllClient,
    pid: str,
    pname: str,
    limit: int,
) -> dict[str, Any]:
    """Fetch and aggregate all task data for a single project."""
    live_lane_task_ids = _fetch_live_lane_task_ids(client, pid)
    ready_tasks, _ready_total = _fetch_ready_tasks(client, pid)
    ready_tasks = [
        task
        for task in ready_tasks
        if task.get("id") not in live_lane_task_ids
        and not _task_has_checkpoint(task.get("id"), pid)
    ]
    ready_count = len(ready_tasks)
    blocked_tasks, blocked_count = _fetch_blocked_tasks(client, pid, limit)
    active_tasks, active_count, stale_tasks, stale_count = _fetch_active_stale(
        client, pid, live_lane_task_ids, limit
    )
    return {
        "project_id": pid,
        "project_name": pname,
        "ready_tasks": sorted(ready_tasks, key=task_sort_key),
        "ready_count": ready_count,
        "blocked_tasks": sorted(blocked_tasks, key=task_sort_key),
        "blocked_count": blocked_count,
        "active_tasks": active_tasks,
        "active_count": active_count,
        "stale_tasks": stale_tasks,
        "stale_count": stale_count,
    }


def _render_project_result_lines(r: dict[str, Any], limit: int) -> list[str]:
    """Render the ready/blocked/active/stale summary lines for one project."""
    pid = r["project_id"]
    parts = [f"{r['ready_count']} ready"]
    if r["blocked_count"]:
        parts.append(f"{r['blocked_count']} blocked")
    if r["active_count"]:
        parts.append(f"{r['active_count']} active")
    if r["stale_count"]:
        parts.append(f"{r['stale_count']} stale")
    lines = ["", f"{pid} ({', '.join(parts)})"]

    for task in r["active_tasks"][:limit]:
        status = task.get("status", "running")
        lines.append(_format_task_line(task, prefix="~") + f" [{status}]")

    for task in r["stale_tasks"][:limit]:
        lines.append(_format_task_line(task, prefix="?") + " [stale-running]")

    for task in r["blocked_tasks"][:limit]:
        lines.append(_format_task_line(task, prefix="!"))

    for task in r["ready_tasks"][:limit]:
        prefix = "*" if task.get("task_type") == "bug" else " "
        lines.append(_format_task_line(task, prefix=prefix))

    if not r["blocked_tasks"] and not r["ready_tasks"] and not r["active_tasks"]:
        lines.append("  (no pending tasks)")
    return lines


def render_ready_all_compact(results: list[dict[str, Any]], limit_per_project: int) -> str:
    """Render the canonical ready-all compact text from aggregated project results."""
    total_ready = sum(r["ready_count"] for r in results)
    total_blocked = sum(r["blocked_count"] for r in results)
    total_active = sum(r["active_count"] for r in results)
    total_stale = sum(r["stale_count"] for r in results)

    lines = [
        (
            f"READY-ALL[{total_ready} ready, {total_blocked} blocked, "
            f"{total_active} active, {total_stale} stale across {len(results)} projects]"
        )
    ]
    for result in results:
        lines.extend(_render_project_result_lines(result, limit_per_project))
    lines.append(
        f"\nTOTAL: {total_ready} ready | {total_blocked} blocked | {total_active} active | {total_stale} stale"
    )
    return "\n".join(lines)


def list_ready_all(
    limit_per_project: int,
    client: ReadyAllClient,
) -> None:
    """List ready and blocked tasks across all projects."""
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

    results = [
        _collect_project_data(client, p.get("id") or p.get("project_id", ""), p.get("name", ""), limit_per_project)
        for p in projects
    ]

    results.sort(key=lambda r: (-(r["blocked_count"]), -(r["stale_count"]), -(r["active_count"]), -(r["ready_count"])))
    print(render_ready_all_compact(results, limit_per_project))
