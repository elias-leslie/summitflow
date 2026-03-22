"""Tests for st agents CLI memory-config controls."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.agents import app

runner = CliRunner()


class TestAgentMemoryConfigUpdate:
    """Tests for granular memory-config updates on `st agents update`."""

    def test_update_merges_memory_config_flags_into_existing_agent(self) -> None:
        current_agent = {
            "slug": "debugger",
            "memory_config": {
                "include_references": True,
                "continuity_enabled": False,
                "audience_tags": ["existing-tag"],
                "exclude_tags": ["deprecated"],
            },
        }

        with (
            patch("cli.commands.agents.agents_api", side_effect=[current_agent, {"slug": "debugger"}]) as mock_agents_api,
            patch("cli.commands.agents._print_agent"),
        ):
            result = runner.invoke(
                app,
                [
                    "update",
                    "debugger",
                    "--memory-enabled",
                    "--continuity-enabled",
                    "--continuity-max-sessions",
                    "7",
                    "--add-audience-tags",
                    "jenny-relevant,memory-system",
                    "--remove-exclude-tags",
                    "deprecated",
                    "--change-reason",
                    "route memory to debugger",
                ],
            )

        assert result.exit_code == 0
        assert mock_agents_api.call_args_list[0].args == ("GET", "/debugger")
        assert mock_agents_api.call_args_list[1].args == ("PUT", "/debugger")
        assert mock_agents_api.call_args_list[1].kwargs["json"] == {
            "memory_config": {
                "include_references": True,
                "continuity_enabled": True,
                "audience_tags": ["existing-tag", "jenny-relevant", "memory-system"],
                "exclude_tags": [],
                "injection_enabled": True,
                "continuity_max_sessions": 7,
            },
            "change_reason": "route memory to debugger",
        }

    def test_update_initializes_memory_config_when_agent_has_none(self) -> None:
        current_agent = {"slug": "persona", "memory_config": None}

        with (
            patch("cli.commands.agents.agents_api", side_effect=[current_agent, {"slug": "persona"}]) as mock_agents_api,
            patch("cli.commands.agents._print_agent"),
        ):
            result = runner.invoke(
                app,
                [
                    "update",
                    "persona",
                    "--memory-disabled",
                    "--include-references",
                    "--no-include-guardrails",
                    "--audience-tags",
                    "jenny-relevant,memory-system",
                    "--exclude-tags",
                    "stale",
                ],
            )

        assert result.exit_code == 0
        assert mock_agents_api.call_args_list[1].kwargs["json"]["memory_config"] == {
            "injection_enabled": False,
            "include_references": True,
            "include_guardrails": False,
            "audience_tags": ["jenny-relevant", "memory-system"],
            "exclude_tags": ["stale"],
        }

    def test_update_rejects_granular_memory_flags_with_memory_config_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "memory.json"

        with patch("cli.commands.agents.agents_api") as mock_agents_api:
            result = runner.invoke(
                app,
                [
                    "update",
                    "debugger",
                    "--memory-config-file",
                    str(config_path),
                    "--add-audience-tags",
                    "memory-system",
                ],
            )

        assert result.exit_code == 1
        assert "Use either granular memory-config flags or --memory-config-file/--clear-memory-config, not both" in result.output
        mock_agents_api.assert_not_called()

