"""Tests for st agents CLI memory-config controls."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.agents import app

runner = CliRunner()


def test_create_agent_posts_full_payload(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("You are purpose built.", encoding="utf-8")
    memory_path = tmp_path / "memory.json"
    memory_path.write_text(json.dumps({"include_mandates": True}), encoding="utf-8")

    with (
        patch("cli.commands.agents.agents_api", return_value={"slug": "graphify-semantic-extractor"}) as mock_agents_api,
        patch("cli.commands.agents._print_agent"),
    ):
        result = runner.invoke(
            app,
            [
                "create",
                "graphify-semantic-extractor",
                "Graphify Semantic Extractor",
                "--primary-model",
                "gemini-3-flash-preview",
                "--fallback-model",
                "gemini-3.1-pro-preview",
                "--fallback-model",
                "codex/gpt-5.5",
                "--escalation-model",
                "codex/gpt-5.5",
                "--temperature",
                "0.1",
                "--thinking-level",
                "high",
                "--verbosity-level",
                "low",
                "--non-coding-agent",
                "--system-prompt-file",
                str(prompt_path),
                "--memory-config-file",
                str(memory_path),
            ],
        )

    assert result.exit_code == 0
    assert mock_agents_api.call_args.args == ("POST", "")
    assert mock_agents_api.call_args.kwargs["json"] == {
        "slug": "graphify-semantic-extractor",
        "name": "Graphify Semantic Extractor",
        "system_prompt": "You are purpose built.",
        "primary_model_id": "gemini-3-flash-preview",
        "temperature": 0.1,
        "is_active": True,
        "is_coding_agent": False,
        "thinking_level": "high",
        "verbosity_level": "low",
        "fallback_models": ["gemini-3.1-pro-preview", "codex/gpt-5.5"],
        "escalation_model_id": "codex/gpt-5.5",
        "memory_config": {"include_mandates": True},
    }


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
