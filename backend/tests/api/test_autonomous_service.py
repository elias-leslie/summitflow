"""Tests for autonomous settings service helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.autonomous import update_settings as update_autonomous_endpoint
from app.api.autonomous_models import AutonomousSettingsUpdate
from app.api.autonomous_service import get_autonomous_settings
from app.constants import TASK_TYPE_VALUES
from app.storage.agent_configs import DEFAULT_AGENT_CONFIG, AgentConfig


def test_get_autonomous_settings_reads_extended_agent_config() -> None:
    config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
    config.update(
        {
            "autonomous_frequency_minutes": 45,
            "autonomous_auto_merge_tiers": [1, 2],
            "autonomous_task_types": ["bug", "feature"],
            "upkeep_enabled": True,
            "upkeep_frequency_minutes": 180,
            "upkeep_batch_limit": 4,
            "autonomous_max_tasks_per_day": 7,
            "autonomous_cooldown_minutes": 15,
            "autonomous_allowed_types": ["bug"],
            "autonomous_external_origins": ["agent-hub-context-maintenance"],
            "autonomous_max_self_fix_attempts": 4,
            "autonomous_max_supervisor_attempts": 5,
            "autonomous_max_extensions": 2,
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
    assert settings.upkeep_enabled is True
    assert settings.upkeep_frequency_minutes == 180
    assert settings.upkeep_batch_limit == 4
    assert settings.max_tasks_per_day == 7
    assert settings.cooldown_minutes == 15
    assert settings.allowed_types == ["bug"]
    assert settings.external_origins == ["agent-hub-context-maintenance"]
    assert settings.max_self_fix_attempts == 4
    assert settings.max_supervisor_attempts == 5
    assert settings.max_extensions == 2
    assert not settings.require_review
    assert settings.quality_gate_tools == ["ruff", "types"]
    assert settings.quality_gate_mode == "check"
    assert not settings.quality_gate_fix_enabled


def test_get_autonomous_settings_expands_legacy_default_allowed_types() -> None:
    config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
    config["autonomous_allowed_types"] = ["refactor", "bug", "regression", "feature", "chore", "docs"]

    with patch("app.api.autonomous_service.get_agent_config", return_value=config):
        settings = get_autonomous_settings("test-project")

    assert settings.allowed_types == list(TASK_TYPE_VALUES)


def test_get_autonomous_settings_drops_stale_allowed_types() -> None:
    config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
    config["autonomous_allowed_types"] = ["bug", "docs", "test"]

    with patch("app.api.autonomous_service.get_agent_config", return_value=config):
        settings = get_autonomous_settings("test-project")

    assert settings.allowed_types == ["bug"]


def test_get_autonomous_settings_preserves_explicit_narrow_allowed_types() -> None:
    config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
    config["autonomous_allowed_types"] = ["bug"]

    with patch("app.api.autonomous_service.get_agent_config", return_value=config):
        settings = get_autonomous_settings("test-project")

    assert settings.allowed_types == ["bug"]


@pytest.mark.asyncio
async def test_update_settings_rejects_legacy_local_writer() -> None:
    with (
        patch("app.api.autonomous.validate_project_exists"),
        pytest.raises(HTTPException) as exc,
    ):
        await update_autonomous_endpoint(
            "test-project",
            AutonomousSettingsUpdate(
                enabled=True,
                upkeep_enabled=True,
                frequency_minutes=60,
                quality_gate_mode="check",
            ),
        )

    assert exc.value.status_code == 410
    assert "Agent Hub Automations" in str(exc.value.detail)
