"""Tests for task progress sync helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

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

    def test_plan_context_steps_are_guidance_only_and_are_not_auto_passed(self) -> None:
        client = MagicMock()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "passes": False,
                    "citations_acknowledged_at": "2026-03-09T12:00:00Z",
                    "steps_from_table": [],
                    "steps_source": "plan_context",
                    "steps": [
                        {"step_number": 1, "description": "Implement the change", "passes": False},
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
        assert "1.1:plan-context" in mock_echo.call_args.args[0]

    def test_sync_orders_subtasks_by_dependency_before_passing_dependents(self) -> None:
        client = MagicMock()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.7",
                    "passes": False,
                    "depends_on": ["1.6"],
                    "citations_acknowledged_at": "2026-03-09T12:00:00Z",
                    "steps_from_table": [
                        {"step_number": 1, "passes": True, "status": "pending"},
                    ],
                },
                {
                    "subtask_id": "1.6",
                    "passes": False,
                    "depends_on": [],
                    "citations_acknowledged_at": "2026-03-09T12:00:00Z",
                    "steps_from_table": [
                        {"step_number": 1, "passes": True, "status": "pending"},
                    ],
                },
            ]
        }

        with (
            patch("cli.commands.tasks_progress.STClient", return_value=client),
            patch("cli.commands.tasks_progress.output_success"),
        ):
            sync_progress_command("task-1", acknowledge_none=False)

        assert client.update_subtask.call_args_list == [
            call("task-1", "1.6", passes=True),
            call("task-1", "1.7", passes=True),
        ]
