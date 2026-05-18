"""Tests for subtask completion via `st done` (replaces the retired `st subtask pass`)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from cli.client import APIError
from cli.commands.done_subtask import _resolve_citations_for_subtask, complete_subtask
from cli.commands.subtask import app as subtask_app
from cli.commands.subtask import clear_subtask, list_subtasks
from cli.commands.subtask_validation import is_step_resolved

runner = CliRunner()


class TestIsStepResolved:
    """Tests for the is_step_resolved helper function."""

    def test_passed_step_is_resolved(self) -> None:
        step = {"step_number": 1, "passes": True}
        assert is_step_resolved(step, {1: True})

    def test_unpassed_step_not_resolved(self) -> None:
        step = {"step_number": 1, "passes": False}
        assert not is_step_resolved(step, {1: False})

    def test_missing_passes_field_not_resolved(self) -> None:
        step = {"step_number": 1}
        assert not is_step_resolved(step, {1: False})


class TestSubtaskSurface:
    """The retired `st subtask pass` command must not reappear."""

    def test_subtask_app_no_longer_exposes_pass(self) -> None:
        result = runner.invoke(subtask_app, ["pass", "--help"])
        assert result.exit_code != 0


class TestDoneSubtaskCompletion:
    """Subtask completion + citation flow now lives in `complete_subtask`."""

    def test_acknowledges_none_when_flag_set(self) -> None:
        client = MagicMock()
        _resolve_citations_for_subtask(client, "task-1", "1.1", None, True)
        client.acknowledge_no_citations.assert_called_once_with("task-1", "1.1")
        client.log_citations.assert_not_called()

    def test_logs_inline_citations(self) -> None:
        client = MagicMock()
        _resolve_citations_for_subtask(client, "task-1", "1.1", ["M:abc12345+"], False)
        client.log_citations.assert_called_once_with(
            "task-1", "1.1", ["M:abc12345+"],
        )
        client.acknowledge_no_citations.assert_not_called()

    def test_extracts_citations_from_applied_text(self) -> None:
        client = MagicMock()
        _resolve_citations_for_subtask(
            client,
            "task-1",
            "1.1",
            ["Verified refactor. Applied: [M:42dae24e] [M:c918f298]."],
            False,
        )
        client.log_citations.assert_called_once_with(
            "task-1", "1.1", ["M:42dae24e", "M:c918f298"],
        )

    def test_rejects_conflicting_citation_flags(self) -> None:
        client = MagicMock()
        with pytest.raises(typer.Exit) as exc_info:
            _resolve_citations_for_subtask(client, "task-1", "1.1", ["M:abc12345+"], True)
        assert exc_info.value.exit_code == 1

    def test_complete_subtask_is_idempotent_when_already_passed(self) -> None:
        client = MagicMock()
        client.get_subtasks.return_value = {
            "subtasks": [{"subtask_id": "1.1", "passes": True}]
        }
        result = complete_subtask(client, "1.1", "task-1")
        assert result == {
            "task_id": "task-1",
            "subtask_id": "1.1",
            "action": "noop",
            "merged": False,
        }
        client.update_subtask.assert_not_called()

    def test_complete_subtask_surfaces_dependency_blocker_cleanly(self, capsys) -> None:
        client = MagicMock()
        client.get_subtasks.return_value = {
            "subtasks": [{"subtask_id": "1.2", "passes": False}]
        }
        client.update_subtask.side_effect = APIError(
            400,
            {
                "message": "Cannot pass subtask 1.2; incomplete dependencies: 1.1",
                "incomplete_steps": [],
            },
        )

        with (
            patch("cli.commands.done_subtask._validate_working_tree_clean"),
            patch("cli.commands.done_subtask._get_project_id", return_value=None),
            patch("cli.commands.done_subtask._merge_subtask"),
            pytest.raises(typer.Exit) as exc_info,
        ):
            complete_subtask(client, "1.2", "task-1", acknowledge_none=True)

        assert exc_info.value.exit_code == 1
        stderr = capsys.readouterr().err
        assert "Cannot pass subtask 1.2; incomplete dependencies: 1.1" in stderr
        assert "PL/pgSQL" not in stderr
        assert "CONTEXT" not in stderr

    def test_subtask_list_accepts_task_id_argument(self) -> None:
        client = MagicMock()
        client.get_subtasks.return_value = {
            "subtasks": [{"subtask_id": "1.1", "passes": False}],
            "summary": {"completed": 0, "total": 1, "progress_percent": 0},
        }

        with (
            patch("cli.commands.subtask.STClient", return_value=client),
            patch("cli.commands.subtask.output_subtasks") as mock_output,
        ):
            list_subtasks("task-1", include_steps=False)

        client.get_subtasks.assert_called_once_with("task-1", include_steps=False)
        mock_output.assert_called_once_with(
            [{"subtask_id": "1.1", "passes": False}],
            {"completed": 0, "total": 1, "progress_percent": 0},
        )


class TestClearSubtaskCommand:
    def test_clear_subtask_can_reset_pass_state(self) -> None:
        client = MagicMock()

        with (
            patch("cli.commands.subtask.STClient", return_value=client),
            patch("cli.commands.subtask.output_success"),
        ):
            clear_subtask("1.1", "task-1")

        client.update_subtask.assert_called_once_with("task-1", "1.1", passes=False)
