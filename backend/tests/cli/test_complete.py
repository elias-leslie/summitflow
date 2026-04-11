"""Tests for st complete command ergonomics."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.complete import app

runner = CliRunner()


def test_complete_accepts_message_option(tmp_path: Path) -> None:
    with patch("cli.commands.complete.call_complete") as mock_call:
        mock_call.return_value = {"content": "ok"}

        result = runner.invoke(
            app,
            ["--agent", "persona", "--message", "Say hello"],
        )

    assert result.exit_code == 0
    mock_call.assert_called_once()
    assert mock_call.call_args.args[1] == "Say hello"


def test_complete_uses_file_when_message_missing(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("hello from file")

    with patch("cli.commands.complete.call_complete") as mock_call:
        mock_call.return_value = {"content": "ok"}

        result = runner.invoke(
            app,
            ["--agent", "persona", "--file", str(prompt_file)],
        )

    assert result.exit_code == 0
    assert mock_call.call_args.args[1] == "hello from file"


def test_complete_help_mentions_message_option() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--message" in result.output


def test_complete_execute_tools_defaults_working_dir_to_cwd(tmp_path: Path) -> None:
    cwd = tmp_path / "agent-cwd"
    cwd.mkdir()

    with (
        patch("cli.commands.complete.Path.cwd", return_value=cwd),
        patch("cli.commands.complete.call_complete") as mock_call,
    ):
        mock_call.return_value = {"content": "ok"}

        result = runner.invoke(
            app,
            ["--agent", "persona", "--execute-tools", "--message", "Run tools"],
        )

    assert result.exit_code == 0
    assert mock_call.call_args.args[7] == str(cwd)


def test_complete_explicit_working_dir_wins_over_cwd_default(tmp_path: Path) -> None:
    cwd = tmp_path / "agent-cwd"
    cwd.mkdir()
    explicit = "/tmp/explicit-dir"

    with (
        patch("cli.commands.complete.Path.cwd", return_value=cwd),
        patch("cli.commands.complete.call_complete") as mock_call,
    ):
        mock_call.return_value = {"content": "ok"}

        result = runner.invoke(
            app,
            [
                "--agent", "persona", "--execute-tools", "--working-dir", explicit,
                "--message", "Run tools",
            ],
        )

    assert result.exit_code == 0
    assert mock_call.call_args.args[7] == explicit


def test_complete_supports_no_memory_flag() -> None:
    with patch("cli.commands.complete.call_complete") as mock_call:
        mock_call.return_value = {"content": "ok"}

        result = runner.invoke(
            app,
            ["--agent", "persona", "--no-memory", "--message", "Lean run"],
        )

    assert result.exit_code == 0
    assert mock_call.call_args.args[4] is False


def test_complete_forwards_task_type() -> None:
    with patch("cli.commands.complete.call_complete") as mock_call:
        mock_call.return_value = {"content": "ok"}

        result = runner.invoke(
            app,
            ["--agent", "persona", "--task-type", "heartbeat", "--message", "Lean run"],
        )

    assert result.exit_code == 0
    assert mock_call.call_args.args[16] == "heartbeat"
