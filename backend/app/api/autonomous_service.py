"""Autonomous execution service layer."""

from typing import Any, cast

from ..storage.agent_configs import get_agent_config, update_agent_config
from .autonomous_models import (
    AutonomousSettings,
    AutonomousSettingsUpdate,
)


def get_autonomous_settings(project_id: str) -> AutonomousSettings:
    """Get autonomous settings from agent config."""
    config = get_agent_config(project_id)

    # Extract autonomous-specific settings or use defaults
    enabled = bool(config.get("autonomous_enabled", False))
    freq_raw = config.get("autonomous_frequency_minutes", 30)
    frequency_minutes = int(cast(int, freq_raw) if freq_raw else 30)
    auto_merge_tiers_raw = config.get("autonomous_auto_merge_tiers")
    auto_merge_tiers = list(cast(list[int], auto_merge_tiers_raw)) if auto_merge_tiers_raw else [1]
    task_types_raw = config.get("autonomous_task_types")
    task_types = list(cast(list[str], task_types_raw)) if task_types_raw else ["auto-generated"]

    # Schedule settings
    start_hour = int(config.get("autonomous_start_hour", 0))
    end_hour = int(config.get("autonomous_end_hour", 24))
    max_concurrent = int(config.get("autonomous_max_concurrent", 1))

    return AutonomousSettings(
        enabled=enabled,
        frequency_minutes=frequency_minutes,
        auto_merge_tiers=auto_merge_tiers,
        task_types=task_types,
        start_hour=start_hour,
        end_hour=end_hour,
        max_concurrent=max_concurrent,
    )


def update_autonomous_settings(
    project_id: str, settings: AutonomousSettingsUpdate
) -> AutonomousSettings:
    """Update autonomous settings in agent config."""
    updates: dict[str, Any] = {}

    if settings.enabled is not None:
        updates["autonomous_enabled"] = settings.enabled
    if settings.frequency_minutes is not None:
        updates["autonomous_frequency_minutes"] = settings.frequency_minutes
    if settings.auto_merge_tiers is not None:
        updates["autonomous_auto_merge_tiers"] = settings.auto_merge_tiers
    if settings.task_types is not None:
        updates["autonomous_task_types"] = settings.task_types
    # Schedule settings
    if settings.start_hour is not None:
        updates["autonomous_start_hour"] = settings.start_hour
    if settings.end_hour is not None:
        updates["autonomous_end_hour"] = settings.end_hour
    if settings.max_concurrent is not None:
        updates["autonomous_max_concurrent"] = settings.max_concurrent

    if updates:
        update_agent_config(project_id, updates)  # type: ignore[arg-type]

    return get_autonomous_settings(project_id)
