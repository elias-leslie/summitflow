"""Tests for task progress sync helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cli.commands.tasks_progress import sync_progress_command


class TestSyncProgressCommand:
    def test_syncs_completed_subtask_and_acknowledges_none(self) -> None:
        client = MagicMock()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "passes": False,
                    "citations_acknowledged_at": None,
                    "steps_from_table": [
                        {"step_number": 1, "passes": True, "status": "pending"},
                    ],
                }
            ]
        }

        with (
            patch("cli.commands.tasks_progress.STClient", return_value=client),
            patch("cli.commands.tasks_progress.output_success") as mock_success,
        ):
            sync_progress_command("task-1", acknowledge_none=True)

        client.acknowledge_no_citations.assert_called_once_with("task-1", "1.1")
        client.update_subtask.assert_called_once_with("task-1", "1.1", passes=True)
        assert "1.1" in mock_success.call_args.args[0]

    def test_skips_when_citations_not_acknowledged_and_none_not_requested(self) -> None:
        client = MagicMock()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "passes": False,
                    "citations_acknowledged_at": None,
                    "steps_from_table": [
                        {"step_number": 1, "passes": True, "status": "pending"},
                    ],
                }
            ]
        }

        with (
            patch("cli.commands.tasks_progress.STClient", return_value=client),
            patch("typer.echo") as mock_echo,
        ):
            sync_progress_command("task-1", acknowledge_none=False)

        client.acknowledge_no_citations.assert_not_called()
        client.update_subtask.assert_not_called()
        assert "1.1:citations" in mock_echo.call_args.args[0]

    def test_skips_subtask_with_unresolved_steps(self) -> None:
        client = MagicMock()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "passes": False,
                    "citations_acknowledged_at": "2026-03-09T12:00:00Z",
                    "steps_from_table": [
                        {"step_number": 1, "passes": False, "status": "pending"},
                    ],
                }
            ]
        }

        with (
            patch("cli.commands.tasks_progress.STClient", return_value=client),
            patch("typer.echo") as mock_echo,
        ):
            sync_progress_command("task-1", acknowledge_none=False)

        client.update_subtask.assert_not_called()
        assert "1.1:steps-1" in mock_echo.call_args.args[0]

    def test_uses_steps_field_when_steps_from_table_missing(self) -> None:
        client = MagicMock()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "passes": False,
                    "citations_acknowledged_at": "2026-03-09T12:00:00Z",
                    "steps": [
                        {"step_number": 1, "passes": True, "status": "pending"},
                    ],
                }
            ]
        }

        with (
            patch("cli.commands.tasks_progress.STClient", return_value=client),
            patch("cli.commands.tasks_progress.output_success"),
        ):
            sync_progress_command("task-1", acknowledge_none=False)

        client.update_subtask.assert_called_once_with("task-1", "1.1", passes=True)
