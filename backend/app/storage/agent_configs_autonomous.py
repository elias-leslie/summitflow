"""Autonomous execution configuration for agent configs.

Access control (enabled, schedule, hours) is now managed centrally by
Agent Hub's project_permissions table. This module retains execution
behavior helpers (concurrency, cooldown, self-healing, etc.).
"""

from __future__ import annotations

from .agent_configs import get_agent_config

LEGACY_DEFAULT_ALLOWED_TYPES = ["refactor", "bug", "regression", "feature", "chore", "docs"]
DEFAULT_ALLOWED_TYPES = [*LEGACY_DEFAULT_ALLOWED_TYPES, "task", "debt", "test"]


def normalize_allowed_task_types(allowed_types: object) -> list[str] | None:
    """Return normalized allowed task types, preserving explicit narrow lists."""
    if not allowed_types:
        return None
    if not isinstance(allowed_types, list):
        return None
    values = [str(t) for t in allowed_types]
    if values == LEGACY_DEFAULT_ALLOWED_TYPES:
        return DEFAULT_ALLOWED_TYPES.copy()
    return values


def get_max_tasks_per_day(project_id: str) -> int | None:
    """Get maximum tasks per day limit for autonomous execution.

    Args:
        project_id: Project ID

    Returns:
        Max tasks per day, or None for unlimited
    """
    config = get_agent_config(project_id)
    max_tasks = config.get("autonomous_max_tasks_per_day")
    if max_tasks is None:
        return None
    return int(str(max_tasks))


def get_cooldown_minutes(project_id: str) -> int:
    """Get cooldown period between autonomous task dispatches.

    Args:
        project_id: Project ID

    Returns:
        Cooldown in minutes (default: 0)
    """
    config = get_agent_config(project_id)
    value = config.get("autonomous_cooldown_minutes", 0)
    return int(str(value)) if value is not None else 0


def get_allowed_task_types(project_id: str) -> list[str] | None:
    """Get allowed task types for autonomous execution.

    Args:
        project_id: Project ID

    Returns:
        List of allowed task types, or None for all types allowed
    """
    config = get_agent_config(project_id)
    return normalize_allowed_task_types(config.get("autonomous_allowed_types"))


def get_max_self_fix_attempts(project_id: str) -> int:
    """Get max self-fix attempts before supervisor escalation.

    Args:
        project_id: Project ID

    Returns:
        Max self-fix attempts (default: 3)
    """
    config = get_agent_config(project_id)
    value = config.get("autonomous_max_self_fix_attempts", 3)
    return int(str(value)) if value is not None else 3


def get_max_supervisor_attempts(project_id: str) -> int:
    """Get max supervisor-guided attempts before blocking.

    Args:
        project_id: Project ID

    Returns:
        Max supervisor attempts (default: 3)
    """
    config = get_agent_config(project_id)
    value = config.get("autonomous_max_supervisor_attempts", 3)
    return int(str(value)) if value is not None else 3


def get_max_extensions(project_id: str) -> int:
    """Get max extension requests when retry budget exhausted.

    Args:
        project_id: Project ID

    Returns:
        Max extensions (default: 3)
    """
    config = get_agent_config(project_id)
    value = config.get("autonomous_max_extensions", 3)
    return int(str(value)) if value is not None else 3


def get_auto_merge_enabled(project_id: str) -> bool:
    """Check if auto-merge is enabled for autonomous execution.

    Args:
        project_id: Project ID

    Returns:
        True if auto-merge is enabled (default: True)
    """
    config = get_agent_config(project_id)
    return bool(config.get("autonomous_auto_merge_enabled", True))


def get_require_review(project_id: str) -> bool:
    """Check if AI review is required before merge.

    Args:
        project_id: Project ID

    Returns:
        True if review is required (default: False — deterministic gates replaced the LLM review tier)
    """
    config = get_agent_config(project_id)
    return bool(config.get("autonomous_require_review", False))
