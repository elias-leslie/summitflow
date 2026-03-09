"""Tests for task lifecycle CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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
