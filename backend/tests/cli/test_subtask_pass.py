"""Tests for subtask pass helpers and command behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer

from cli.commands.subtask import clear_subtask, pass_subtask
from cli.commands.subtask_validation import is_step_resolved


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


class TestPassSubtaskCommand:
    def test_pass_subtask_can_acknowledge_none_inline(self) -> None:
        client = MagicMock()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "steps_from_table": [{"step_number": 1, "passes": True}],
                }
            ]
        }

        with (
            patch("cli.commands.subtask.STClient", return_value=client),
            patch("cli.commands.subtask.output_success"),
        ):
            pass_subtask("1.1", "task-1", None, True)

        client.acknowledge_no_citations.assert_called_once_with("task-1", "1.1")
        client.update_subtask.assert_called_once_with("task-1", "1.1", passes=True)

    def test_pass_subtask_can_log_inline_citations(self) -> None:
        client = MagicMock()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "steps_from_table": [{"step_number": 1, "passes": True}],
                }
            ]
        }

        with (
            patch("cli.commands.subtask.STClient", return_value=client),
            patch("cli.commands.subtask.output_success"),
        ):
            pass_subtask("1.1", "task-1", ["M:abc12345+"], False)

        client.log_citations.assert_called_once_with("task-1", "1.1", ["M:abc12345+"])
        client.update_subtask.assert_called_once_with("task-1", "1.1", passes=True)

    def test_pass_subtask_rejects_conflicting_citation_flags(self) -> None:
        with pytest.raises(typer.Exit) as exc_info:
            pass_subtask("1.1", "task-1", ["M:abc12345+"], True)

        assert exc_info.value.exit_code == 1


class TestClearSubtaskCommand:
    def test_clear_subtask_can_reset_pass_state(self) -> None:
        client = MagicMock()

        with (
            patch("cli.commands.subtask.STClient", return_value=client),
            patch("cli.commands.subtask.output_success"),
        ):
            clear_subtask("1.1", "task-1")

        client.update_subtask.assert_called_once_with("task-1", "1.1", passes=False)
