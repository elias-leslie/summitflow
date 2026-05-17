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

    def test_pause_task_cleans_safe_residue(self) -> None:
        from cli.commands.tasks_lifecycle import pause_task_command

        client = MagicMock()
        client.pause_task.return_value = {
            "id": "task-123",
            "project_id": "summitflow",
            "status": "paused",
        }
        checkpoint = MagicMock(task_id="task-123")
        from cli.commands.cleanup_analysis import CleanupAction

        analysis = MagicMock()
        analysis.action = CleanupAction.ALREADY_MERGED

        with (
            patch("cli.commands.tasks_lifecycle.STClient", return_value=client),
            patch("cli.commands.tasks_lifecycle.output_task"),
            patch("cli.commands.tasks_lifecycle.output_success") as mock_success,
            patch("cli.lib.checkpoint.get_active_checkpoints", return_value=[checkpoint]),
            patch("cli.commands.cleanup_analysis.analyze_checkpoint", return_value=analysis),
            patch("cli.commands.cleanup_analysis.cleanup_checkpoint", return_value=(True, "Removed")),
        ):
            pause_task_command("task-123", "")

        mock_success.assert_called_once_with("checkpoint_cleaned")


class TestResumeRemoved:
    """`st resume` collapsed into `st reopen`; the command must not be importable."""

    def test_resume_task_command_no_longer_exists(self) -> None:
        import cli.commands.tasks_lifecycle as lifecycle

        assert not hasattr(lifecycle, "resume_task_command")


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
