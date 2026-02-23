"""Guard conditions for autonomous task dispatch.

Provides validation checks for scheduling, concurrency, autonomous mode, and system health.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from typing import Any

from app.storage import agent_configs
from app.storage import tasks as task_store
from app.storage.connection import get_connection


def check_autonomous_enabled(project_id: str) -> dict[str, Any] | None:
    """Check if autonomous mode is enabled via Agent Hub API.

    Replaces local agent_configs check with centralized Agent Hub
    permission system. Fail-closed on error.

    Args:
        project_id: Project to check

    Returns:
        Error dict if disabled/error, None if enabled
    """
    import httpx

    try:
        resp = httpx.get(
            f"http://localhost:8003/api/projects/{project_id}/execution-permission",
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("allowed"):
            return {
                "status": "disabled",
                "reason": data.get("reason", "not_allowed"),
            }
        return None
    except Exception as e:
        return {
            "status": "disabled",
            "reason": f"agent_hub_unreachable: {e}",
        }



def check_concurrency_limit(project_id: str) -> dict[str, Any] | None:
    """Check if concurrency limit has been reached.

    Args:
        project_id: Project to check

    Returns:
        Error dict if at limit, None if under limit
    """
    config = agent_configs.get_agent_config(project_id)
    max_concurrent = int(config.get("autonomous_max_concurrent", 1))
    running_count = task_store.count_running_tasks(project_id)

    if running_count >= max_concurrent:
        return {
            "status": "concurrency_limit",
            "running_count": running_count,
            "max_concurrent": max_concurrent,
        }
    return None


def check_max_tasks_per_day(project_id: str) -> dict[str, Any] | None:
    """Check if daily task limit has been reached.

    Args:
        project_id: Project to check

    Returns:
        Error dict if at daily limit, None if under limit
    """
    max_tasks = agent_configs.get_max_tasks_per_day(project_id)
    if max_tasks is None:
        return None  # Unlimited

    completed_today = task_store.count_completed_tasks_today(project_id)
    if completed_today >= max_tasks:
        return {
            "status": "daily_limit",
            "completed_today": completed_today,
            "max_tasks_per_day": max_tasks,
        }
    return None


def check_cooldown_period(project_id: str) -> dict[str, Any] | None:
    """Check if cooldown period has elapsed since last dispatch.

    Args:
        project_id: Project to check

    Returns:
        Error dict if in cooldown, None if cooldown elapsed
    """
    cooldown_minutes = agent_configs.get_cooldown_minutes(project_id)
    if cooldown_minutes == 0:
        return None  # No cooldown

    # Get the most recently started task
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT started_at
            FROM tasks
            WHERE project_id = %s
              AND started_at IS NOT NULL
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (project_id,),
        )
        row = cur.fetchone()

    if not row or not row[0]:
        return None  # No previous tasks

    last_dispatch = row[0]
    cooldown_until = last_dispatch + timedelta(minutes=cooldown_minutes)
    now = datetime.now(last_dispatch.tzinfo)  # Use same timezone

    if now < cooldown_until:
        remaining_minutes = int((cooldown_until - now).total_seconds() / 60)
        return {
            "status": "cooldown",
            "last_dispatch": last_dispatch.isoformat(),
            "cooldown_minutes": cooldown_minutes,
            "remaining_minutes": remaining_minutes,
        }
    return None


def check_allowed_task_type(project_id: str, task_type: str | None) -> dict[str, Any] | None:
    """Check if task type is allowed for autonomous execution.

    Args:
        project_id: Project to check
        task_type: Task type to validate

    Returns:
        Error dict if type not allowed, None if allowed
    """
    allowed_types = agent_configs.get_allowed_task_types(project_id)
    if allowed_types is None:
        return None  # All types allowed

    if task_type not in allowed_types:
        return {
            "status": "type_not_allowed",
            "task_type": task_type,
            "allowed_types": allowed_types,
        }
    return None


def check_system_health(project_id: str) -> dict[str, Any] | None:
    """Check if critical system services are healthy.

    Checks postgres, redis, and backend health. Blocks dispatch if any
    critical service is unhealthy.

    Args:
        project_id: Project to check

    Returns:
        Error dict if any critical service is unhealthy, None if all healthy
    """
    failing_services: list[str] = []
    details: dict[str, str] = {}

    # Check PostgreSQL connectivity
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        details["postgres"] = "healthy"
    except Exception as e:
        failing_services.append("postgres")
        details["postgres"] = f"unhealthy: {e}"

    # Check Redis connectivity
    try:
        import redis

        r = redis.Redis.from_url("redis://localhost:6379/1", socket_timeout=3)
        r.ping()
        details["redis"] = "healthy"
    except Exception as e:
        failing_services.append("redis")
        details["redis"] = f"unhealthy: {e}"

    # Check backend process is alive (via systemd)
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "summitflow-backend"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.stdout.strip() == "active":
            details["backend"] = "healthy"
        else:
            failing_services.append("backend")
            details["backend"] = f"unhealthy: {result.stdout.strip()}"
    except Exception:
        # Can't check — don't block dispatch for monitoring failures
        details["backend"] = "check_unavailable"

    if failing_services:
        return {
            "status": "unhealthy",
            "failing_services": failing_services,
            "details": details,
        }
    return None


def check_task_dispatchable(task: dict[str, object]) -> dict[str, object] | None:
    """Check if a task is in a state that allows dispatch.

    Args:
        task: Task dict with at least 'id', 'status', and optionally 'claimed_by'

    Returns:
        Error dict if task cannot be dispatched, None if dispatchable
    """
    task_id = task["id"]
    status = task["status"]

    if status == "running":
        return {"status": "already_running", "task_id": task_id}

    if status not in ("queue", "pending", "blocked"):
        return {"status": "skipped", "task_id": task_id, "reason": f"status={status}"}

    return None


def validate_autonomous_dispatch(
    project_id: str, task_type: str | None = None
) -> dict[str, Any] | None:
    """Run all guard checks for autonomous dispatch.

    Args:
        project_id: Project to validate
        task_type: Optional task type to validate (if checking a specific task)

    Returns:
        Error dict if any check fails, None if all pass
    """
    if error := check_autonomous_enabled(project_id):
        return error

    if error := check_system_health(project_id):
        return error

    if error := check_concurrency_limit(project_id):
        return error

    if error := check_max_tasks_per_day(project_id):
        return error

    if error := check_cooldown_period(project_id):
        return error

    if task_type is not None and (error := check_allowed_task_type(project_id, task_type)):
        return error

    return None
