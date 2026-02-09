"""Guard conditions for autonomous task dispatch.

Provides validation checks for scheduling, concurrency, and autonomous mode.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.storage import agent_configs
from app.storage import tasks as task_store


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


def validate_autonomous_dispatch(project_id: str) -> dict[str, Any] | None:
    """Run all guard checks for autonomous dispatch.

    Args:
        project_id: Project to validate

    Returns:
        Error dict if any check fails, None if all pass
    """
    if error := check_autonomous_enabled(project_id):
        return error

    if error := check_autonomous_hours(project_id):
        return error

    if error := check_concurrency_limit(project_id):
        return error

    return None
