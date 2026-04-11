"""Tests for st prompt CLI behaviors."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli._output_state import set_compact_output
from cli.commands.prompt import app
from cli.commands.prompt_formatters import format_prompt_restored, format_prompt_revisions

runner = CliRunner()


class TestPromptHistoryCommands:
    def test_revisions_forwards_limit_to_prompt_api(self) -> None:
        with (
            patch("cli.commands.prompt.prompt_api", return_value={"revisions": []}) as mock_prompt_api,
            patch("cli.commands.prompt.format_prompt_revisions") as mock_format,
        ):
            result = runner.invoke(app, ["revisions", "persona-heartbeat-instructions", "--limit", "7"])

        assert result.exit_code == 0
        mock_prompt_api.assert_called_once_with(
            "GET",
            "/persona-heartbeat-instructions/revisions",
            params={"limit": 7},
            tool_name="st prompt revisions",
        )
        mock_format.assert_called_once_with("persona-heartbeat-instructions", {"revisions": []})

    def test_restore_forwards_change_reason_to_prompt_api(self) -> None:
        with (
            patch("cli.commands.prompt.prompt_api", return_value={"slug": "persona-heartbeat-instructions"}) as mock_prompt_api,
            patch("cli.commands.prompt.format_prompt_restored") as mock_format,
        ):
            result = runner.invoke(
                app,
                [
                    "restore",
                    "persona-heartbeat-instructions",
                    "rev-12345678",
                    "--change-reason",
                    "rollback bad edit",
                ],
            )

        assert result.exit_code == 0
        mock_prompt_api.assert_called_once_with(
            "POST",
            "/persona-heartbeat-instructions/revisions/rev-12345678/restore",
            json={"change_reason": "rollback bad edit"},
            tool_name="st prompt restore",
        )
        mock_format.assert_called_once_with(
            "persona-heartbeat-instructions",
            "rev-12345678",
            {"slug": "persona-heartbeat-instructions"},
        )

    def test_update_forwards_change_reason_to_prompt_api(self, tmp_path: Path) -> None:
        content_file = tmp_path / "prompt.md"
        content_file.write_text("Keep signal, cut filler.\n", encoding="utf-8")

        with patch("cli.commands.prompt.prompt_api", return_value={"content": "Keep signal, cut filler.\n"}) as mock_prompt_api:
            result = runner.invoke(
                app,
                [
                    "update",
                    "persona-heartbeat-instructions",
                    "--file",
                    str(content_file),
                    "--change-reason",
                    "compress duplicate wording",
                ],
            )

        assert result.exit_code == 0
        mock_prompt_api.assert_called_once_with(
            "PUT",
            "/persona-heartbeat-instructions",
            json={
                "content": "Keep signal, cut filler.\n",
                "change_reason": "compress duplicate wording",
            },
        )


class TestPromptHistoryFormatters:
    def test_format_prompt_revisions_compact(self, capsys) -> None:
        set_compact_output(True)
        try:
            format_prompt_revisions(
                "persona-heartbeat-instructions",
                {
                    "revisions": [
                        {
                            "id": "rev-12345678",
                            "action": "update",
                            "created_at": "2026-04-11T05:00:00Z",
                            "changed_by": "api",
                            "change_reason": "compress duplicate wording",
                        }
                    ]
                },
            )
        finally:
            set_compact_output(False)

        captured = capsys.readouterr().out
        assert "PROMPT_REVISIONS[1]:slug=persona-heartbeat-instructions" in captured
        assert "rev-1234 [update] at=2026-04-11T05:00:00Z by=api" in captured
        assert "reason=compress duplicate wording" in captured

    def test_format_prompt_restored_compact(self, capsys) -> None:
        set_compact_output(True)
        try:
            format_prompt_restored(
                "persona-heartbeat-instructions",
                "rev-12345678",
                {
                    "content": "Keep signal, cut filler.\n",
                    "updated_at": "2026-04-11T05:15:00Z",
                },
            )
        finally:
            set_compact_output(False)

        captured = capsys.readouterr().out
        assert "PROMPT_RESTORED:persona-heartbeat-instructions:rev=rev-1234|1L|updated_at=2026-04-11T05:15:00Z" in captured
