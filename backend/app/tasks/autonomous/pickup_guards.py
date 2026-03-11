"""Guard conditions for autonomous task dispatch: scheduling, concurrency, and health checks."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from typing import Any

from app.config import REDIS_URL
from app.services._agent_hub_config import AGENT_HUB_URL
from app.storage import agent_configs
from app.storage import tasks as task_store
from app.storage.connection import get_connection

# Constants
_AGENT_HUB_URL = f"{AGENT_HUB_URL}/api/projects/{{project_id}}/execution-permission"
_REDIS_URL = f"{REDIS_URL}/1"
_REDIS_TIMEOUT = 3
_BACKEND_SERVICE = "summitflow-backend"
_HTTP_TIMEOUT = 5.0
_SUBPROCESS_TIMEOUT = 5
_DISPATCHABLE_STATUSES = ("queue", "pending", "blocked")


def check_autonomous_enabled(project_id: str) -> dict[str, Any] | None:
    """Return error dict if autonomous mode is disabled/unreachable, else None."""
    import httpx
    try:
        resp = httpx.get(_AGENT_HUB_URL.format(project_id=project_id), timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("allowed"):
            return {"status": "disabled", "reason": data.get("reason", "not_allowed")}
        # Autonomous execution requires write access — reject read-only projects
        # early instead of wasting agent sessions that fail on every tool call.
        tier = data.get("permission_tier", "")
        if tier in ("read", "off"):
            return {"status": "disabled", "reason": f"permission_tier_{tier}_insufficient_for_execution"}
        return None
    except Exception as e:
        return {"status": "disabled", "reason": f"agent_hub_unreachable: {e}"}


def check_concurrency_limit(project_id: str) -> dict[str, Any] | None:
    """Return error dict if concurrency limit reached, else None."""
    config = agent_configs.get_agent_config(project_id)
    max_concurrent = int(config.get("autonomous_max_concurrent", 1))
    running_count = task_store.count_running_tasks(project_id)
    if running_count >= max_concurrent:
        return {"status": "concurrency_limit", "running_count": running_count, "max_concurrent": max_concurrent}
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
    with get_connection() as conn, conn.cursor() as cur:
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
        with get_connection() as conn, conn.cursor() as cur:
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
    # Backend (systemd)
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", _BACKEND_SERVICE],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.stdout.strip() == "active":
            details["backend"] = "healthy"
        else:
            failing.append("backend")
            details["backend"] = f"unhealthy: {result.stdout.strip()}"
    except Exception:
        details["backend"] = "check_unavailable"
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


def validate_autonomous_dispatch(project_id: str, task_type: str | None = None) -> dict[str, Any] | None:
    """Run all guard checks; return first error dict or None if all pass."""
    checks = [check_autonomous_enabled, check_system_health, check_concurrency_limit,
               check_max_tasks_per_day, check_cooldown_period]
    for check in checks:
        if error := check(project_id):
            return error
    if task_type is not None:
        return check_allowed_task_type(project_id, task_type)
    return None
