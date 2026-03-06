"""Tests for st memory CLI behaviors."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.memory import app

runner = CliRunner()


class TestMemoryUpdateContentInput:
    """Tests for safe content ingestion in `st memory update`."""

    def test_update_accepts_content_from_file(self, tmp_path: Path) -> None:
        """`--content-file` should load the file contents and forward them to update_impl."""
        content_file = tmp_path / "episode.md"
        content_file.write_text("Use /commit_it when available.\n", encoding="utf-8")

        with patch("cli.commands.memory.update_impl") as mock_update_impl:
            result = runner.invoke(app, ["update", "abc12345", "--content-file", str(content_file)])

        assert result.exit_code == 0
        mock_update_impl.assert_called_once_with(
            "abc12345",
            "Use /commit_it when available.\n",
            None,
            None,
            None,
            None,
        )

    def test_update_accepts_content_from_stdin(self) -> None:
        """`--content-file -` should read content from stdin."""
        with patch("cli.commands.memory.update_impl") as mock_update_impl:
            result = runner.invoke(
                app,
                ["update", "abc12345", "--content-file", "-"],
                input="Literal [work] and `backticks` should survive.\n",
            )

        assert result.exit_code == 0
        mock_update_impl.assert_called_once_with(
            "abc12345",
            "Literal [work] and `backticks` should survive.\n",
            None,
            None,
            None,
            None,
        )

    def test_update_rejects_inline_and_file_content_together(self, tmp_path: Path) -> None:
        """`--content` and `--content-file` together should error clearly."""
        content_file = tmp_path / "episode.md"
        content_file.write_text("content\n", encoding="utf-8")

        with patch("cli.commands.memory.update_impl") as mock_update_impl:
            result = runner.invoke(
                app,
                [
                    "update",
                    "abc12345",
                    "--content",
                    "inline",
                    "--content-file",
                    str(content_file),
                ],
            )

        assert result.exit_code == 2
        assert "Specify only one of --content or --content-file" in result.output
        mock_update_impl.assert_not_called()
