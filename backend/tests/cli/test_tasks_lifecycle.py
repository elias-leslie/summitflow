"""Tests for task lifecycle CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestPauseTaskCommand:
    def test_pause_task_updates_status_with_reason(self) -> None:
        from cli.commands.tasks_lifecycle import pause_task_command

        client = MagicMock()
        client.pause_task.return_value = {"id": "task-123", "status": "paused"}

        with (
            patch("cli.commands.tasks_lifecycle.STClient", return_value=client),
            patch("cli.commands.tasks_lifecycle.output_task") as mock_output,
        ):
            pause_task_command("task-123", "Waiting on review")

        client.pause_task.assert_called_once_with("task-123", reason="Waiting on review")
        rendered = mock_output.call_args.args[0]
        assert rendered["status"] == "paused"
        assert rendered["pause_reason"] == "Waiting on review"


class TestResumeTaskCommand:
    def test_resume_task_updates_status_to_pending_with_reason(self) -> None:
        from cli.commands.tasks_lifecycle import resume_task_command

        client = MagicMock()
        client.resume_task.return_value = {"id": "task-123", "status": "pending"}

        with (
            patch("cli.commands.tasks_lifecycle.STClient", return_value=client),
            patch("cli.commands.tasks_lifecycle.output_task") as mock_output,
        ):
            resume_task_command("task-123", "Ready again")

        client.resume_task.assert_called_once_with("task-123", reason="Ready again")
        rendered = mock_output.call_args.args[0]
        assert rendered["status"] == "pending"
        assert rendered["resume_reason"] == "Ready again"


class TestReopenTaskCommand:
    def test_reopen_task_updates_status_to_pending_with_reason(self) -> None:
        from cli.commands.tasks_lifecycle import reopen_task_command

        client = MagicMock()
        client.reopen_task.return_value = {"id": "task-123", "status": "pending"}

        with (
            patch("cli.commands.tasks_lifecycle.STClient", return_value=client),
            patch("cli.commands.tasks_lifecycle.output_task") as mock_output,
        ):
            reopen_task_command("task-123", "False completion during reconcile")

        client.reopen_task.assert_called_once_with(
            "task-123",
            reason="False completion during reconcile",
        )
        mock_output.assert_called_once()
        rendered = mock_output.call_args.args[0]
        assert rendered["status"] == "pending"
        assert rendered["reopen_reason"] == "False completion during reconcile"

    def test_reopen_task_omits_empty_reason(self) -> None:
        from cli.commands.tasks_lifecycle import reopen_task_command

        client = MagicMock()
        client.reopen_task.return_value = {"id": "task-123", "status": "pending"}

        with (
            patch("cli.commands.tasks_lifecycle.STClient", return_value=client),
            patch("cli.commands.tasks_lifecycle.output_task") as mock_output,
        ):
            reopen_task_command("task-123", "")

        client.reopen_task.assert_called_once_with("task-123", reason=None)
        rendered = mock_output.call_args.args[0]
        assert "reopen_reason" not in rendered
