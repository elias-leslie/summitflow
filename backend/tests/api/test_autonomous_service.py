"""Tests for autonomous settings service helpers."""

from __future__ import annotations

from unittest.mock import patch

from app.api.autonomous import _validate_update
from app.api.autonomous_models import AutonomousSettingsUpdate
from app.api.autonomous_service import (
    get_autonomous_settings,
    update_autonomous_settings,
)
from app.storage.agent_configs import DEFAULT_AGENT_CONFIG, AgentConfig


def test_get_autonomous_settings_reads_extended_agent_config() -> None:
    config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
    config.update(
        {
            "autonomous_frequency_minutes": 45,
            "autonomous_auto_merge_tiers": [1, 2],
            "autonomous_task_types": ["bug", "feature"],
            "autonomous_max_tasks_per_day": 7,
            "autonomous_cooldown_minutes": 15,
            "autonomous_allowed_types": ["bug"],
            "autonomous_max_self_fix_attempts": 4,
            "autonomous_max_supervisor_attempts": 5,
            "autonomous_max_extensions": 2,
            "autonomous_auto_merge_enabled": False,
            "autonomous_require_review": False,
            "quality_gate_tools": ["ruff", "types"],
            "quality_gate_mode": "check",
            "quality_gate_fix_enabled": False,
        }
    )

    with patch("app.api.autonomous_service.get_agent_config", return_value=config):
        settings = get_autonomous_settings("test-project")

    assert settings.frequency_minutes == 45
    assert settings.auto_merge_tiers == [1, 2]
    assert settings.task_types == ["bug", "feature"]
    assert settings.max_tasks_per_day == 7
    assert settings.cooldown_minutes == 15
    assert settings.allowed_types == ["bug"]
    assert settings.max_self_fix_attempts == 4
    assert settings.max_supervisor_attempts == 5
    assert settings.max_extensions == 2
    assert not settings.auto_merge_enabled
    assert not settings.require_review
    assert settings.quality_gate_tools == ["ruff", "types"]
    assert settings.quality_gate_mode == "check"
    assert not settings.quality_gate_fix_enabled


def test_update_autonomous_settings_writes_partial_agent_config() -> None:
    updated_config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
    updated_config.update(
        {
            "autonomous_frequency_minutes": 60,
            "autonomous_auto_merge_enabled": False,
            "quality_gate_mode": "check",
        }
    )

    with (
        patch("app.api.autonomous_service.update_agent_config") as mock_update,
        patch("app.api.autonomous_service.get_agent_config", return_value=updated_config),
    ):
        settings = update_autonomous_settings(
            "test-project",
            AutonomousSettingsUpdate(
                frequency_minutes=60,
                auto_merge_enabled=False,
                quality_gate_mode="check",
            ),
        )

    mock_update.assert_called_once_with(
        "test-project",
        {
            "autonomous_frequency_minutes": 60,
            "autonomous_auto_merge_enabled": False,
            "quality_gate_mode": "check",
        },
    )
    assert settings.frequency_minutes == 60
    assert not settings.auto_merge_enabled
    assert settings.quality_gate_mode == "check"


def test_validate_update_accepts_vitest_quality_gate_tool() -> None:
    _validate_update(
        AutonomousSettingsUpdate(quality_gate_tools=["biome", "tsc", "vitest"])
    )
