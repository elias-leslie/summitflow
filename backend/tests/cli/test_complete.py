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
