"""Autonomous execution service layer.

Access control (enabled, schedule hours) is now managed by Agent Hub's
project_permissions. This service handles execution behavior settings only.
"""

from __future__ import annotations

from typing import TypedDict

from ..storage.agent_configs import AgentConfig, get_agent_config
from ..storage.agent_configs_autonomous import normalize_allowed_task_types
from .autonomous_models import AutonomousSettings


class _CoreSettingsPayload(TypedDict):
    frequency_minutes: int
    auto_merge_tiers: list[int]
    task_types: list[str]
    upkeep_enabled: bool
    upkeep_frequency_minutes: int
    upkeep_batch_limit: int
    max_concurrent: int
    max_tasks_per_day: int | None
    cooldown_minutes: int
    allowed_types: list[str] | None
    external_origins: list[str] | None


class _AdvancedSettingsPayload(TypedDict):
    max_self_fix_attempts: int
    max_supervisor_attempts: int
    max_extensions: int
    require_review: bool
    quality_gate_tools: list[str]
    quality_gate_mode: str
    quality_gate_fix_enabled: bool


def _parse_core_settings(config: AgentConfig) -> _CoreSettingsPayload:
    """Parse execution behavior settings from config."""
    frequency_minutes = int(config.get("autonomous_frequency_minutes", 30) or 30)
    auto_merge_tiers_raw = config.get("autonomous_auto_merge_tiers")
    auto_merge_tiers = list(auto_merge_tiers_raw) if auto_merge_tiers_raw else [1]
    task_types_raw = config.get("autonomous_task_types")
    task_types = list(task_types_raw) if task_types_raw else ["auto-generated"]
    upkeep_enabled = bool(config.get("upkeep_enabled", False))
    upkeep_frequency_minutes = int(config.get("upkeep_frequency_minutes", 120) or 120)
    upkeep_batch_limit = int(config.get("upkeep_batch_limit", 5) or 5)
    max_tasks_per_day_raw = config.get("autonomous_max_tasks_per_day")
    max_tasks_per_day = int(max_tasks_per_day_raw) if max_tasks_per_day_raw else None
    allowed_types = normalize_allowed_task_types(config.get("autonomous_allowed_types"))
    external_origins_raw = config.get("autonomous_external_origins")
    external_origins = (
        [str(origin).strip() for origin in external_origins_raw if str(origin).strip()]
        if isinstance(external_origins_raw, list)
        else None
    )
    return {
        "frequency_minutes": frequency_minutes,
        "auto_merge_tiers": auto_merge_tiers,
        "task_types": task_types,
        "upkeep_enabled": upkeep_enabled,
        "upkeep_frequency_minutes": upkeep_frequency_minutes,
        "upkeep_batch_limit": upkeep_batch_limit,
        "max_concurrent": int(config.get("autonomous_max_concurrent") or 1),
        "max_tasks_per_day": max_tasks_per_day,
        "cooldown_minutes": int(config.get("autonomous_cooldown_minutes", 0) or 0),
        "allowed_types": allowed_types,
        "external_origins": external_origins,
    }


def _parse_advanced_settings(config: AgentConfig) -> _AdvancedSettingsPayload:
    """Parse self-healing, auto-merge, and quality gate settings from config."""
    qg_tools_raw = config.get("quality_gate_tools", [])
    return {
        "max_self_fix_attempts": int(str(config.get("autonomous_max_self_fix_attempts", 3))),
        "max_supervisor_attempts": int(str(config.get("autonomous_max_supervisor_attempts", 3))),
        "max_extensions": int(str(config.get("autonomous_max_extensions", 3))),
        "require_review": bool(config.get("autonomous_require_review", False)),
        "quality_gate_tools": list(qg_tools_raw) if qg_tools_raw else [],
        "quality_gate_mode": str(config.get("quality_gate_mode", "quick")),
        "quality_gate_fix_enabled": bool(config.get("quality_gate_fix_enabled", True)),
    }


def get_autonomous_settings(project_id: str) -> AutonomousSettings:
    """Get autonomous settings from agent config."""
    config = get_agent_config(project_id)
    return AutonomousSettings(**_parse_core_settings(config), **_parse_advanced_settings(config))
