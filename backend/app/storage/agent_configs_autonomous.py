"""Autonomous execution configuration for agent configs."""

from __future__ import annotations

from typing import TypedDict

from .agent_configs import AgentConfig, get_agent_config, update_agent_config


class AutonomousScheduleConfig(TypedDict):
    """Autonomous execution schedule configuration."""

    enabled: bool
    start_hour: int  # 0-23
    end_hour: int  # 1-24 (24 = end of day)
    max_concurrent: int  # 1-3


def is_autonomous_enabled(project_id: str) -> bool:
    """Check if autonomous execution is enabled for a project.

    Args:
        project_id: Project ID

    Returns:
        True if autonomous execution is enabled
    """
    config = get_agent_config(project_id)
    return bool(config.get("autonomous_enabled", False))


def get_autonomous_schedule(project_id: str) -> AutonomousScheduleConfig:
    """Get autonomous execution schedule for a project.

    Args:
        project_id: Project ID

    Returns:
        AutonomousScheduleConfig with schedule settings
    """
    config = get_agent_config(project_id)
    return {
        "enabled": config.get("autonomous_enabled", False),
        "start_hour": config.get("autonomous_start_hour", 0),
        "end_hour": config.get("autonomous_end_hour", 24),
        "max_concurrent": config.get("autonomous_max_concurrent", 1),
    }


def is_within_autonomous_hours(project_id: str, current_hour: int) -> bool:
    """Check if current hour is within the autonomous execution window.

    Args:
        project_id: Project ID
        current_hour: Current hour (0-23)

    Returns:
        True if current_hour is within [start_hour, end_hour)
    """
    schedule = get_autonomous_schedule(project_id)
    if not schedule["enabled"]:
        return False

    start = schedule["start_hour"]
    end = schedule["end_hour"]

    if start < end:
        return start <= current_hour < end
    return current_hour >= start or current_hour < end


def update_autonomous_schedule(
    project_id: str,
    start_hour: int | None = None,
    end_hour: int | None = None,
    max_concurrent: int | None = None,
) -> AgentConfig:
    """Update autonomous execution schedule for a project.

    Args:
        project_id: Project ID
        start_hour: Hour (0-23) when execution can start
        end_hour: Hour (1-24) when execution must stop
        max_concurrent: Max concurrent tasks (1-3)

    Returns:
        Updated config

    Raises:
        ValueError: If invalid values provided
    """
    updates: AgentConfig = {}

    if start_hour is not None:
        if not 0 <= start_hour <= 23:
            raise ValueError("start_hour must be 0-23")
        updates["autonomous_start_hour"] = start_hour

    if end_hour is not None:
        if not 1 <= end_hour <= 24:
            raise ValueError("end_hour must be 1-24")
        updates["autonomous_end_hour"] = end_hour

    if max_concurrent is not None:
        if not 1 <= max_concurrent <= 3:
            raise ValueError("max_concurrent must be 1-3")
        updates["autonomous_max_concurrent"] = max_concurrent

    return update_agent_config(project_id, updates)
