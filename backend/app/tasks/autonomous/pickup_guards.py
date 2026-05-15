"""Guard conditions for autonomous task dispatch: scheduling, concurrency, and health checks."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from app.config import DEFAULT_API_BASE, REDIS_URL
from app.services._agent_hub_config import AGENT_HUB_URL, build_agent_hub_headers
from app.storage import agent_configs
from app.storage import tasks as task_store
from app.storage.connection import get_cursor

# Constants
_AGENT_HUB_URL = f"{AGENT_HUB_URL}/api/projects/{{project_id}}/execution-permission"
_AGENT_HUB_SESSIONS_URL = f"{AGENT_HUB_URL}/api/sessions"
_REDIS_URL = f"{REDIS_URL}/1"
_REDIS_TIMEOUT = 3
_HTTP_TIMEOUT = 5.0
_DISPATCHABLE_STATUSES = ("pending", "failed")
_IGNORED_CONCURRENCY_SOURCES = {"codex-transcript-sync"}
_STALE_LIFECYCLE_STATES = {"dead_candidate", "reapable"}
_FINAL_HEALTH_STATES = {"completed", "failed", "error"}
_FINAL_TASK_STATUSES = {"completed", "failed", "cancelled", "abandoned", "closed"}


def check_agent_hub_execution_permission(
    project_id: str,
    *,
    require_enabled: bool = True,
) -> dict[str, Any] | None:
    """Return error dict if Agent Hub permission cannot support execution."""
    import httpx
    try:
        resp = httpx.get(
            _AGENT_HUB_URL.format(project_id=project_id),
            headers=build_agent_hub_headers(request_source="sf-pipeline"),
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if require_enabled and not data.get("allowed"):
            return {"status": "disabled", "reason": data.get("reason", "not_allowed")}
        # Execution requires trusted project access. Manual dispatch may bypass
        # the auto-enabled flag, but never the project permission tier.
        tier = str(data.get("permission_tier", "")).strip().lower()
        if tier in {"write", "yolo"}:
            tier = "full"
        if tier != "full":
            return {"status": "disabled", "reason": f"permission_tier_{tier}_insufficient_for_execution"}
        return None
    except Exception as e:
        return {"status": "disabled", "reason": f"agent_hub_unreachable: {e}"}


def check_autonomous_enabled(project_id: str) -> dict[str, Any] | None:
    """Return error dict if autonomous mode is disabled/unreachable, else None."""
    return check_agent_hub_execution_permission(project_id, require_enabled=True)


def _session_task_is_terminal(session: dict[str, Any], project_id: str | None) -> bool:
    external_id = str(session.get("external_id") or "").strip()
    if not external_id.startswith("task-"):
        return False
    try:
        task = task_store.get_task(external_id)
    except Exception:
        return False
    if not task or (project_id and task.get("project_id") != project_id):
        return False
    return str(task.get("status") or "").strip().lower() in _FINAL_TASK_STATUSES


def _session_counts_for_concurrency(
    session: dict[str, Any],
    *,
    project_id: str | None = None,
    exclude_task_id: str | None = None,
) -> bool:
    if str(session.get("status") or "").lower() != "active":
        return False
    external_id = str(session.get("external_id") or "").strip()
    live_activity = session.get("live_activity")
    if isinstance(live_activity, dict):
        lifecycle_state = str(live_activity.get("lifecycle_state") or "").strip().lower()
        if lifecycle_state in _STALE_LIFECYCLE_STATES:
            return False
        health = str(live_activity.get("health") or "").strip().lower()
        if health in _FINAL_HEALTH_STATES:
            return False
    if exclude_task_id and external_id == exclude_task_id:
        return False
    if not external_id.startswith("task-"):
        return False
    if _session_task_is_terminal(session, project_id):
        return False
    request_source = str(session.get("request_source") or "").strip().lower()
    return request_source not in _IGNORED_CONCURRENCY_SOURCES


def count_active_agent_hub_sessions(project_id: str, *, exclude_task_id: str | None = None) -> int:
    """Count live Agent Hub sessions that should consume autonomous project capacity."""
    import httpx

    resp = httpx.get(
        _AGENT_HUB_SESSIONS_URL,
        headers=build_agent_hub_headers(request_source="sf-pipeline"),
        params={"project_id": project_id, "status": "active", "page_size": 100},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    sessions = payload.get("sessions", [])
    if not isinstance(sessions, list):
        return 0
    return sum(
        1
        for session in sessions
        if isinstance(session, dict)
        and _session_counts_for_concurrency(session, project_id=project_id, exclude_task_id=exclude_task_id)
    )


def get_concurrency_snapshot(project_id: str, *, exclude_task_id: str | None = None) -> dict[str, int]:
    """Return current task/session capacity pressure for autonomous dispatch."""
    config = agent_configs.get_agent_config(project_id)
    max_concurrent = int(config.get("autonomous_max_concurrent", 1))
    running_count = task_store.count_running_tasks(project_id, exclude_task_id=exclude_task_id)
    active_session_count = count_active_agent_hub_sessions(project_id, exclude_task_id=exclude_task_id)
    active_count = max(running_count, active_session_count)
    return {
        "running_count": running_count,
        "active_session_count": active_session_count,
        "active_count": active_count,
        "max_concurrent": max_concurrent,
        "remaining_capacity": max(0, max_concurrent - active_count),
    }


def check_concurrency_limit(project_id: str, *, exclude_task_id: str | None = None) -> dict[str, Any] | None:
    """Return error dict if task/session concurrency limit reached, else None."""
    try:
        snapshot = get_concurrency_snapshot(project_id, exclude_task_id=exclude_task_id)
    except Exception as exc:
        return {
            "status": "concurrency_unavailable",
            "reason": f"agent_hub_sessions_unreachable: {exc}",
        }
    if snapshot["active_count"] >= snapshot["max_concurrent"]:
        return {"status": "concurrency_limit", **snapshot}
    return None


def check_max_tasks_per_day(project_id: str) -> dict[str, Any] | None:
    """Return error dict if daily task limit reached, else None."""
    max_tasks = agent_configs.get_max_tasks_per_day(project_id)
    if max_tasks is None:
        return None
    completed_today = task_store.count_completed_tasks_today(project_id)
    if completed_today >= max_tasks:
        return {"status": "daily_limit", "completed_today": completed_today, "max_tasks_per_day": max_tasks}
    return None


def check_cooldown_period(project_id: str) -> dict[str, Any] | None:
    """Return error dict if within cooldown window, else None."""
    cooldown_minutes = agent_configs.get_cooldown_minutes(project_id)
    if cooldown_minutes == 0:
        return None
    with get_cursor() as cur:
        cur.execute(
            "SELECT started_at FROM tasks WHERE project_id = %s"
            " AND started_at IS NOT NULL ORDER BY started_at DESC LIMIT 1",
            (project_id,),
        )
        row = cur.fetchone()
    if not row or not row[0]:
        return None
    last_dispatch = row[0]
    cooldown_until = last_dispatch + timedelta(minutes=cooldown_minutes)
    now = datetime.now(last_dispatch.tzinfo)
    if now < cooldown_until:
        remaining = int((cooldown_until - now).total_seconds() / 60)
        return {"status": "cooldown", "last_dispatch": last_dispatch.isoformat(),
                "cooldown_minutes": cooldown_minutes, "remaining_minutes": remaining}
    return None


def check_allowed_task_type(project_id: str, task_type: str | None) -> dict[str, Any] | None:
    """Return error dict if task type is not allowed, else None."""
    allowed_types = agent_configs.get_allowed_task_types(project_id)
    if allowed_types is None:
        return None
    if task_type not in allowed_types:
        return {"status": "type_not_allowed", "task_type": task_type, "allowed_types": allowed_types}
    return None


def check_system_health(project_id: str) -> dict[str, Any] | None:
    """Return error dict if any critical service is unhealthy, else None."""
    failing: list[str] = []
    details: dict[str, str] = {}
    # Postgres
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
        details["postgres"] = "healthy"
    except Exception as e:
        failing.append("postgres")
        details["postgres"] = f"unhealthy: {e}"
    # Redis
    try:
        import redis
        redis.Redis.from_url(_REDIS_URL, socket_timeout=_REDIS_TIMEOUT).ping()
        details["redis"] = "healthy"
    except Exception as e:
        failing.append("redis")
        details["redis"] = f"unhealthy: {e}"
    # Backend (HTTP health check — works in both Docker and systemd runtimes)
    # If the health check itself is unavailable, don't block dispatch — the
    # service may still be running; only explicit non-200 responses count.
    try:
        import httpx
        backend_url = DEFAULT_API_BASE
        health_url = backend_url.rstrip("/api").rstrip("/") + "/health"
        resp = httpx.get(health_url, timeout=_HTTP_TIMEOUT)
        if resp.status_code == 200:
            details["backend"] = "healthy"
        else:
            failing.append("backend")
            details["backend"] = f"unhealthy: status={resp.status_code}"
    except Exception:
        # Health endpoint unreachable (connection refused, timeout, etc.)
        # — treat as unknown rather than unhealthy to avoid blocking dispatch.
        details["backend"] = "unknown: health check unavailable"
    if failing:
        return {"status": "unhealthy", "failing_services": failing, "details": details}
    return None


def check_task_dispatchable(task: dict[str, object]) -> dict[str, object] | None:
    """Return error dict if task cannot be dispatched, else None."""
    task_id, status = task["id"], task["status"]
    if status == "running":
        return {"status": "already_running", "task_id": task_id}
    if status not in _DISPATCHABLE_STATUSES:
        return {"status": "skipped", "task_id": task_id, "reason": f"status={status}"}
    return None


def validate_autonomous_dispatch(
    project_id: str,
    task_type: str | None = None,
    *,
    require_enabled: bool = True,
    exclude_task_id: str | None = None,
    skip_concurrency: bool = False,
) -> dict[str, Any] | None:
    """Run all guard checks; return first error dict or None if all pass."""
    def permission_check(project: str) -> dict[str, Any] | None:
        return check_agent_hub_execution_permission(
            project,
            require_enabled=require_enabled,
        )

    def concurrency_check(project: str) -> dict[str, Any] | None:
        return check_concurrency_limit(project, exclude_task_id=exclude_task_id)

    checks: list[Callable[[str], dict[str, Any] | None]] = [check_system_health]
    if not skip_concurrency:
        checks.append(concurrency_check)
    checks.extend([check_max_tasks_per_day, check_cooldown_period])
    checks.insert(0, permission_check)
    for check in checks:
        if error := check(project_id):
            return error
    if task_type is not None:
        return check_allowed_task_type(project_id, task_type)
    return None
