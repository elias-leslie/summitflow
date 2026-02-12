"""Guard conditions for autonomous task dispatch.

Provides validation checks for scheduling, concurrency, and autonomous mode.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.storage import agent_configs
from app.storage import tasks as task_store
from app.storage.connection import get_connection


def check_autonomous_enabled(project_id: str) -> dict[str, Any] | None:
    """Check if autonomous mode is enabled.

    Args:
        project_id: Project to check

    Returns:
        Error dict if disabled, None if enabled
    """
    if not agent_configs.is_autonomous_enabled(project_id):
        return {
            "status": "disabled",
            "reason": "autonomous_enabled=false",
        }
    return None


def check_autonomous_hours(project_id: str) -> dict[str, Any] | None:
    """Check if current time is within autonomous hours.

    Args:
        project_id: Project to check

    Returns:
        Error dict if outside hours, None if within hours
    """
    current_hour = datetime.now().hour
    if not agent_configs.is_within_autonomous_hours(project_id, current_hour):
        schedule = agent_configs.get_autonomous_schedule(project_id)
        return {
            "status": "outside_hours",
            "current_hour": current_hour,
            "start_hour": schedule.get("start_hour", 0),
            "end_hour": schedule.get("end_hour", 24),
        }
    return None


def check_concurrency_limit(project_id: str) -> dict[str, Any] | None:
    """Check if concurrency limit has been reached.

    Args:
        project_id: Project to check

    Returns:
        Error dict if at limit, None if under limit
    """
    schedule = agent_configs.get_autonomous_schedule(project_id)
    max_concurrent = schedule.get("max_concurrent", 1)
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

    if error := check_autonomous_hours(project_id):
        return error

    if error := check_concurrency_limit(project_id):
        return error

    if error := check_max_tasks_per_day(project_id):
        return error

    if error := check_cooldown_period(project_id):
        return error

    if task_type is not None:
        if error := check_allowed_task_type(project_id, task_type):
            return error

    return None
