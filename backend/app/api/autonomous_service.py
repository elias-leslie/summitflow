"""Autonomous execution service layer."""

from __future__ import annotations

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

    # Frequency limits
    max_tasks_per_day_raw = config.get("autonomous_max_tasks_per_day")
    max_tasks_per_day = int(str(max_tasks_per_day_raw)) if max_tasks_per_day_raw else None
    cooldown_minutes = int(str(config.get("autonomous_cooldown_minutes", 0)))

    # Allowed task types
    allowed_types_raw = config.get("autonomous_allowed_types")
    allowed_types = list(cast(list[str], allowed_types_raw)) if allowed_types_raw else None

    # Model tier preference
    preferred_model_tier = str(config.get("autonomous_preferred_model_tier", "standard"))

    # Self-healing configuration
    max_self_fix_attempts = int(str(config.get("autonomous_max_self_fix_attempts", 3)))
    max_supervisor_attempts = int(str(config.get("autonomous_max_supervisor_attempts", 3)))
    max_extensions = int(str(config.get("autonomous_max_extensions", 3)))

    # Auto-merge control
    auto_merge_enabled = bool(config.get("autonomous_auto_merge_enabled", True))
    require_review = bool(config.get("autonomous_require_review", True))

    return AutonomousSettings(
        enabled=enabled,
        frequency_minutes=frequency_minutes,
        auto_merge_tiers=auto_merge_tiers,
        task_types=task_types,
        start_hour=start_hour,
        end_hour=end_hour,
        max_concurrent=max_concurrent,
        max_tasks_per_day=max_tasks_per_day,
        cooldown_minutes=cooldown_minutes,
        allowed_types=allowed_types,
        preferred_model_tier=preferred_model_tier,
        max_self_fix_attempts=max_self_fix_attempts,
        max_supervisor_attempts=max_supervisor_attempts,
        max_extensions=max_extensions,
        auto_merge_enabled=auto_merge_enabled,
        require_review=require_review,
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

    # Frequency limits
    if settings.max_tasks_per_day is not None:
        updates["autonomous_max_tasks_per_day"] = settings.max_tasks_per_day
    if settings.cooldown_minutes is not None:
        updates["autonomous_cooldown_minutes"] = settings.cooldown_minutes

    # Allowed task types
    if settings.allowed_types is not None:
        updates["autonomous_allowed_types"] = settings.allowed_types

    # Model tier preference
    if settings.preferred_model_tier is not None:
        updates["autonomous_preferred_model_tier"] = settings.preferred_model_tier

    # Self-healing configuration
    if settings.max_self_fix_attempts is not None:
        updates["autonomous_max_self_fix_attempts"] = settings.max_self_fix_attempts
    if settings.max_supervisor_attempts is not None:
        updates["autonomous_max_supervisor_attempts"] = settings.max_supervisor_attempts
    if settings.max_extensions is not None:
        updates["autonomous_max_extensions"] = settings.max_extensions

    # Auto-merge control
    if settings.auto_merge_enabled is not None:
        updates["autonomous_auto_merge_enabled"] = settings.auto_merge_enabled
    if settings.require_review is not None:
        updates["autonomous_require_review"] = settings.require_review

    if updates:
        update_agent_config(project_id, updates)  # type: ignore[arg-type]

    return get_autonomous_settings(project_id)
