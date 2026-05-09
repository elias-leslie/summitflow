"""Tests for autonomous settings service helpers."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, _Call, patch

import pytest

from app.api.autonomous import _sync_auto_exec_permission, _validate_update
from app.api.autonomous import update_settings as update_autonomous_endpoint
from app.api.autonomous_models import AutonomousSettings, AutonomousSettingsUpdate
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
            "upkeep_enabled": True,
            "upkeep_frequency_minutes": 180,
            "upkeep_batch_limit": 4,
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
    assert settings.upkeep_enabled is True
    assert settings.upkeep_frequency_minutes == 180
    assert settings.upkeep_batch_limit == 4
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


def test_get_autonomous_settings_expands_legacy_default_allowed_types() -> None:
    config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
    config["autonomous_allowed_types"] = ["refactor", "bug", "regression", "feature", "chore", "docs"]

    with patch("app.api.autonomous_service.get_agent_config", return_value=config):
        settings = get_autonomous_settings("test-project")

    assert settings.allowed_types == [
        "refactor",
        "bug",
        "regression",
        "feature",
        "chore",
        "docs",
        "task",
        "debt",
        "test",
    ]


def test_get_autonomous_settings_preserves_explicit_narrow_allowed_types() -> None:
    config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
    config["autonomous_allowed_types"] = ["bug"]

    with patch("app.api.autonomous_service.get_agent_config", return_value=config):
        settings = get_autonomous_settings("test-project")

    assert settings.allowed_types == ["bug"]


def test_update_autonomous_settings_writes_partial_agent_config() -> None:
    updated_config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
    updated_config.update(
        {
            "autonomous_frequency_minutes": 60,
            "upkeep_enabled": True,
            "upkeep_batch_limit": 6,
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
                upkeep_enabled=True,
                upkeep_batch_limit=6,
                auto_merge_enabled=False,
                quality_gate_mode="check",
            ),
        )

    mock_update.assert_called_once_with(
        "test-project",
        {
            "autonomous_frequency_minutes": 60,
            "upkeep_enabled": True,
            "upkeep_batch_limit": 6,
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


def test_validate_update_accepts_ready_ranked_task_types() -> None:
    _validate_update(AutonomousSettingsUpdate(allowed_types=["task", "debt", "test"]))


@pytest.mark.asyncio
async def test_sync_auto_exec_permission_preserves_existing_agent_hub_fields() -> None:
    with (
        patch(
            "app.api.autonomous._fetch_agent_hub_project_permission",
            return_value={
                "project_id": "test-project",
                "permission_tier": "full",
                "auto_exec_enabled": False,
                "execution_start_hour": 1,
                "execution_end_hour": 23,
                "root_path": "/repo",
                "daily_cost_budget_usd": 5.0,
                "monthly_cost_budget_usd": 100.0,
                "budget_alert_threshold": 0.9,
            },
        ),
        patch("app.api.autonomous.sync_agent_hub_project_permission", new_callable=AsyncMock) as mock_sync,
    ):
        await _sync_auto_exec_permission("test-project", True)

    await_args = cast(_Call, mock_sync.await_args)
    args = await_args.args
    assert args[0] == "test-project"
    assert args[1].permission_tier == "full"
    assert args[1].auto_exec_enabled is True
    assert args[1].execution_start_hour == 1
    assert args[1].execution_end_hour == 23
    assert args[1].root_path == "/repo"
    assert args[1].daily_cost_budget_usd == 5.0
    assert args[1].monthly_cost_budget_usd == 100.0
    assert args[1].budget_alert_threshold == 0.9
    assert args[2] == "/repo"


@pytest.mark.asyncio
async def test_update_settings_syncs_agent_hub_permission_when_enabled_present() -> None:
    settings = AutonomousSettings()

    with (
        patch("app.api.autonomous.validate_project_exists"),
        patch("app.api.autonomous._update_settings", return_value=settings),
        patch("app.api.autonomous._sync_auto_exec_permission", new_callable=AsyncMock) as mock_sync,
        patch("app.api.autonomous._settings_with_execution_permission", new_callable=AsyncMock, return_value=settings) as mock_settings,
    ):
        result = await update_autonomous_endpoint(
            "test-project",
            AutonomousSettingsUpdate(enabled=True),
        )

    assert result == settings
    mock_sync.assert_awaited_once_with("test-project", True)
    mock_settings.assert_awaited_once_with("test-project")
