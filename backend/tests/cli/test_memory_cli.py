"""Tests for st memory CLI behaviors."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import typer
from typer.testing import CliRunner

from cli.commands.memory import app
from cli.commands.memory_crud import save_impl, update_impl
from cli.commands.memory_formatters import format_list_compact

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
        mock_update_impl.assert_called_once()
        args = mock_update_impl.call_args.args
        assert args[0] == "abc12345"
        assert args[1] == "Use /commit_it when available.\n"
        assert args[2:] == (None, None, None, None, None, False)

    def test_update_accepts_content_from_stdin(self) -> None:
        """`--content-file -` should read content from stdin."""
        with patch("cli.commands.memory.update_impl") as mock_update_impl:
            result = runner.invoke(
                app,
                ["update", "abc12345", "--content-file", "-"],
                input="Literal [work] and `backticks` should survive.\n",
            )

        assert result.exit_code == 0
        mock_update_impl.assert_called_once()
        args = mock_update_impl.call_args.args
        assert args[0] == "abc12345"
        assert args[1] == "Literal [work] and `backticks` should survive.\n"
        assert args[2:] == (None, None, None, None, None, False)

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


class TestMemorySaveContentInput:
    """Tests for safe content ingestion in `st memory save`."""

    def test_save_accepts_content_from_file(self, tmp_path: Path) -> None:
        """`--content-file` should load content for save."""
        content_file = tmp_path / "episode.md"
        content_file.write_text("**Mandate**: Use dt for all quality checks.\n", encoding="utf-8")

        with patch("cli.commands.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "--content-file",
                    str(content_file),
                    "--summary",
                    "Use dt for checks",
                ],
            )

        assert result.exit_code == 0
        args = mock_save_impl.call_args.args
        assert args[1] == "**Mandate**: Use dt for all quality checks.\n"

    def test_save_accepts_content_from_stdin(self) -> None:
        """`--content-file -` should read save content from stdin."""
        with patch("cli.commands.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "--content-file",
                    "-",
                    "--summary",
                    "Use dt for checks",
                ],
                input="**Mandate**: Use dt for all quality checks.\n",
            )

        assert result.exit_code == 0
        args = mock_save_impl.call_args.args
        assert args[1] == "**Mandate**: Use dt for all quality checks.\n"

    def test_save_rejects_inline_and_file_content_together(self, tmp_path: Path) -> None:
        """`save` should reject inline content combined with --content-file."""
        content_file = tmp_path / "episode.md"
        content_file.write_text("content\n", encoding="utf-8")

        with patch("cli.commands.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "inline content",
                    "--content-file",
                    str(content_file),
                    "--summary",
                    "Use dt for checks",
                ],
            )

        assert result.exit_code == 2
        assert "Specify only one of --content or --content-file" in result.output
        mock_save_impl.assert_not_called()


class TestMemoryFormatCommand:
    """Tests for the mechanical memory formatter helper."""

    def test_format_builds_standard_episode_and_summary(self) -> None:
        result = runner.invoke(
            app,
            [
                "format",
                "--tier",
                "mandate",
                "--instruction",
                "Use exact tier headers for every memory episode",
                "--prohibition",
                "Never use custom bold topics for mandate content",
                "--why",
                "retrieval and citation depend on clear authority cues",
            ],
        )

        assert result.exit_code == 0
        assert "summary: exact tier headers for every memory" in result.output.lower()
        assert "CONTENT:" in result.output
        assert "**Mandate**: Use exact tier headers for every memory episode." in result.output
        assert "Never use custom bold topics for mandate content." in result.output
        assert "Why: retrieval and citation depend on clear authority cues." in result.output


class TestMemoryTagOptions:
    """Tests for tag-aware save/update CLI plumbing."""

    def test_save_forwards_tags_to_impl(self) -> None:
        """`st memory save --tags` should wire tags through the public CLI."""
        with patch("cli.commands.memory.save_impl") as mock_save_impl:
            result = runner.invoke(
                app,
                [
                    "save",
                    "**Topic**: Tag finance memories.",
                    "--summary",
                    "Tag finance memory",
                    "--tags",
                    "finance-relevant,portfolio",
                ],
            )

        assert result.exit_code == 0
        args = mock_save_impl.call_args.args
        assert args[1:] == (
            "**Topic**: Tag finance memories.",
            "Tag finance memory",
            "reference",
            80,
            None,
            False,
            None,
            "finance-relevant,portfolio",
            "global",
            None,
        )

    def test_update_forwards_tags_to_impl(self) -> None:
        """`st memory update --tags` should wire tag replacement through the CLI."""
        with patch("cli.commands.memory.update_impl") as mock_update_impl:
            result = runner.invoke(
                app,
                [
                    "update",
                    "abc12345",
                    "--tags",
                    "finance-relevant",
                ],
            )

        assert result.exit_code == 0
        args = mock_update_impl.call_args.args
        assert args == ("abc12345", None, None, None, None, None, "finance-relevant", False)

    def test_update_impl_rejects_tags_and_clear_tags_together(self) -> None:
        """Tag replacement and clearing are mutually exclusive."""
        with patch("cli.commands.memory_crud.typer.echo") as mock_echo:
            try:
                update_impl("abc12345", None, None, None, None, None, "finance-relevant", True)
            except typer.Exit as exc:
                assert exc.exit_code == 1
            else:
                raise AssertionError("Expected typer.Exit when both --tags and --clear-tags are provided")

        mock_echo.assert_called_once_with("Error: Specify only one of --tags or --clear-tags")

    def test_save_impl_applies_tags_after_learning_is_saved(self) -> None:
        """Save should apply requested tags using the memory tags endpoint."""
        out = SimpleNamespace(is_compact=True)
        with (
            patch("cli.commands.memory_crud.validate_save_inputs", return_value="Tag finance memory"),
            patch("cli.commands.memory_crud.validate_content_format"),
            patch("cli.commands.memory_crud.agent_hub_request", return_value={"uuid": "abc12345", "status": "provisional"}),
            patch("cli.commands.memory_crud.replace_episode_tags") as mock_replace_tags,
            patch("cli.commands.memory_crud.format_save_compact"),
        ):
            save_impl(
                out,
                "**Topic**: Tag finance memories.",
                "Tag finance memory",
                "reference",
                80,
                None,
                False,
                None,
                "finance-relevant,portfolio",
                "project",
                "portfolio-ai",
            )

        mock_replace_tags.assert_called_once_with("abc12345", ["finance-relevant", "portfolio"])

    def test_update_impl_preserves_existing_tags_when_updating_in_place(self) -> None:
        """Content/tier updates should preserve tags on the existing episode UUID."""
        with (
            patch("cli.commands.memory_crud.fetch_existing_episode", return_value={"uuid": "abc12345", "content": "old", "summary": "Old", "injection_tier": "reference"}),
            patch("cli.commands.memory_crud.fetch_episode_tags", return_value=["finance-relevant"]),
            patch("cli.commands.memory_crud.update_episode_content_or_tier") as mock_update_episode,
            patch("cli.commands.memory_crud.replace_episode_tags") as mock_replace_tags,
            patch("cli.commands.memory_crud.validate_content_format"),
            patch("cli.commands.memory_crud.typer.echo"),
        ):
            update_impl("abc12345", "new content", None, None, None, None, None, False)

        mock_update_episode.assert_called_once_with(
            "abc12345",
            content="new content",
            tier="reference",
        )
        mock_replace_tags.assert_called_once_with("abc12345", ["finance-relevant"])


class TestMemoryListFormatting:
    """Tests for TOON formatting of memory list output."""

    def test_list_formatter_falls_back_to_category(self, capsys) -> None:
        """List output should show tier from API category field when injection_tier is absent."""
        format_list_compact(
            {
                "episodes": [
                    {
                        "uuid": "abc12345-dead-beef-cafe-1234567890ab",
                        "category": "mandate",
                        "summary": "Use dt",
                        "content": "**DT CLI**: Prefer dt.",
                    }
                ],
                "cursor": None,
            }
        )

        out = capsys.readouterr().out
        assert "abc12345 [mandate] summary=Use dt" in out
