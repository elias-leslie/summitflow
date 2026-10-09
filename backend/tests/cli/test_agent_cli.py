"""Tests for st agent command ergonomics."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.agent import app

runner = CliRunner()


def test_agent_run_defaults_to_tool_loop_with_cwd(tmp_path: Path) -> None:
    cwd = tmp_path / "repo"
    cwd.mkdir()

    with (
        patch("cli.commands.agent.Path.cwd", return_value=cwd),
        patch("cli.commands.agent.call_complete") as mock_call,
    ):
        mock_call.return_value = {
            "content": "done",
            "session_id": "sess-1",
            "model": "codex/gpt-5.5",
            "turns": 2,
            "tool_calls_count": 1,
        }

        result = runner.invoke(
            app,
            ["run", "--agent", "explorer", "--project", "portfolio-ai", "--message", "Inspect state"],
        )

    assert result.exit_code == 0
    kwargs = mock_call.call_args.kwargs
    assert kwargs["agent_slug"] == "explorer"
    assert kwargs["project_id"] == "portfolio-ai"
    assert kwargs["execute_tools"] is True
    assert kwargs["working_dir"] == str(cwd)
    assert kwargs["max_turns"] is None
    assert kwargs["tool_name"] == "st agent"
    assert "AGENT status=ok" in result.stderr


def test_agent_run_forwards_read_only_parent_and_errors() -> None:
    with patch("cli.commands.agent.call_complete") as mock_call:
        mock_call.return_value = {
            "content": "Error: bad config",
            "session_id": "sess-2",
            "finish_reason": "error",
            "error": "missing credentials",
            "progress_log": [
                {
                    "status": "tool_result",
                    "message": "Tool failed: bash",
                    "tool_results": [{"name": "bash", "is_error": True}],
                }
            ],
        }

        result = runner.invoke(
            app,
            [
                "run",
                "--agent", "explorer",
                "--read-only",
                "--parent-session", "parent-1",
                "--message", "Inspect only",
            ],
        )

    assert result.exit_code == 1
    kwargs = mock_call.call_args.kwargs
    assert kwargs["read_only"] is True
    assert kwargs["parent_session_id"] == "parent-1"
    assert "AGENT_ERRORS" in result.stderr
    assert "missing credentials" in result.stderr


def test_agent_run_surfaces_recovered_tool_errors() -> None:
    with patch("cli.commands.agent.call_complete") as mock_call:
        mock_call.return_value = {
            "content": "recovered",
            "session_id": "sess-3",
            "finish_reason": "end_turn",
            "error_summary": {
                "items": [
                    {"kind": "tool_output", "tool": "bash", "message": "bash error: command failed"}
                ]
            },
        }

        result = runner.invoke(
            app,
            ["run", "--agent", "explorer", "--message", "Recover from a failed command"],
        )

    assert result.exit_code == 0
    assert "AGENT status=ok" in result.stderr
    assert "AGENT_ERRORS" in result.stderr
    assert "command failed" in result.stderr


def test_agent_run_rejects_removed_adhoc_routing_flags() -> None:
    with patch("cli.commands.agent.call_complete") as mock_call:
        result = runner.invoke(app, ["run", "--adhoc", "--cost", "low_cost", "--message", "x"])

    assert result.exit_code != 0
    mock_call.assert_not_called()


def test_agent_run_requires_exact_agent_slug() -> None:
    with patch("cli.commands.agent.call_complete") as mock_call:
        result = runner.invoke(app, ["run", "--message", "Inspect state"])

    assert result.exit_code == 1
    assert "Missing --agent" in result.stderr
    mock_call.assert_not_called()
