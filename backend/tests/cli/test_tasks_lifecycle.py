"""Tests for task lifecycle CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


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
        with (
            patch("cli.commands.tasks_lifecycle.STClient", return_value=client),
            patch("cli.commands.tasks_lifecycle.output_task"),
            patch("cli.commands.tasks_lifecycle.output_success") as mock_success,
            patch("cli.commands.tasks_lifecycle._cleanup_safe_pause_residue", return_value="checkpoint_cleaned") as cleanup,
        ):
            pause_task_command("123", "")

        cleanup.assert_called_once_with("task-123", "summitflow")
        mock_success.assert_called_once_with("checkpoint_cleaned")


class TestPauseCheckpointCleanup:
    @pytest.fixture
    def safe_checkpoint(self):
        from cli.lib.checkpoint_metadata import SnapshotMeta

        meta = SnapshotMeta("task-123", "summitflow", "main", "2026-10-03T02:00:00Z", "owner")
        with (
            patch("cli.lib.checkpoint_metadata.load_snapshot_meta", return_value=meta) as load,
            patch("cli.lib.checkpoint.get_active_checkpoints", return_value=[]) as active,
            patch("cli.lib.checkpoint.remove_snapshot", return_value=True) as remove,
            patch("app.storage.projects.get_project_root_path", return_value="/project") as root,
            patch("app.storage.tasks.get_task", return_value={"id": "task-123", "project_id": "summitflow", "status": "paused"}) as task,
            patch("cli.lib.commit_workflow.run_git", return_value=MagicMock(returncode=0, stdout="")) as git,
            patch("cli.commands.cleanup_analysis.analyze_checkpoint") as analyze,
        ):
            yield meta, load, active, remove, root, task, git, analyze

    def test_retained_paused_checkpoint_is_cleaned_without_active_lookup(self, safe_checkpoint) -> None:
        from cli.commands.tasks_lifecycle import _cleanup_safe_pause_residue

        _, load, active, remove, _, _, git, analyze = safe_checkpoint
        assert _cleanup_safe_pause_residue("123", "summitflow") == "checkpoint_cleaned"
        assert load.call_count == 2
        load.assert_called_with("task-123")
        remove.assert_called_once_with("task-123", project_id="summitflow")
        active.assert_not_called()
        analyze.assert_not_called()
        assert git.call_args_list[0].args[1] == ["status", "--porcelain", "--untracked-files=all"]
        assert all("fetch" not in call.args[1] for call in git.call_args_list)

    @pytest.mark.parametrize("field,value", [("task_id", "task-other"), ("project_id", "other")])
    def test_foreign_metadata_is_preserved(self, safe_checkpoint, field, value) -> None:
        from cli.commands.tasks_lifecycle import _cleanup_safe_pause_residue

        meta, _, _, remove, _, _, git, _ = safe_checkpoint
        setattr(meta, field, value)
        result = _cleanup_safe_pause_residue("task-123", "summitflow")
        assert result is not None and result.startswith("checkpoint_kept:")
        remove.assert_not_called()
        git.assert_not_called()

    def test_missing_metadata_is_noop(self, safe_checkpoint) -> None:
        from cli.commands.tasks_lifecycle import _cleanup_safe_pause_residue

        _, load, _, remove, _, _, _, _ = safe_checkpoint
        load.return_value = None
        assert _cleanup_safe_pause_residue("task-123", "summitflow") is None
        remove.assert_not_called()

    @pytest.mark.parametrize("returncode,stdout", [(0, " M owned.py"), (1, "")])
    def test_dirty_or_failed_inspection_is_preserved(self, safe_checkpoint, returncode, stdout) -> None:
        from cli.commands.tasks_lifecycle import _cleanup_safe_pause_residue

        _, _, _, remove, _, _, git, _ = safe_checkpoint
        git.return_value = MagicMock(returncode=returncode, stdout=stdout)
        result = _cleanup_safe_pause_residue("task-123", "summitflow")
        assert result is not None and result.startswith("checkpoint_kept:")
        remove.assert_not_called()

    @pytest.mark.parametrize("ref", ["task-123", "task-123/1.2", "task/task-123", "task/task-123/1.2"])
    def test_legacy_task_refs_are_preserved(self, safe_checkpoint, ref) -> None:
        from cli.commands.tasks_lifecycle import _cleanup_safe_pause_residue

        _, _, _, remove, _, _, git, _ = safe_checkpoint
        git.side_effect = [MagicMock(returncode=0, stdout=""), MagicMock(returncode=0, stdout=f"refs/heads/{ref}\n")]
        assert _cleanup_safe_pause_residue("task-123", "summitflow") == "checkpoint_kept:legacy_task_refs"
        remove.assert_not_called()

    def test_unrelated_prefix_ref_does_not_block(self, safe_checkpoint) -> None:
        from cli.commands.tasks_lifecycle import _cleanup_safe_pause_residue

        _, _, _, remove, _, _, git, _ = safe_checkpoint
        git.side_effect = [MagicMock(returncode=0, stdout=""), MagicMock(returncode=0, stdout="refs/heads/task-1234\n")]
        assert _cleanup_safe_pause_residue("task-123", "summitflow") == "checkpoint_cleaned"
        remove.assert_called_once()

    @pytest.mark.parametrize("status", ["running", "pending", "completed"])
    def test_reclaimed_task_is_preserved(self, safe_checkpoint, status) -> None:
        from cli.commands.tasks_lifecycle import _cleanup_safe_pause_residue

        _, _, _, remove, _, task, _, _ = safe_checkpoint
        task.return_value["status"] = status
        result = _cleanup_safe_pause_residue("task-123", "summitflow")
        assert result is not None and result.startswith("checkpoint_kept:")
        remove.assert_not_called()

    def test_replaced_metadata_is_preserved(self, safe_checkpoint) -> None:
        from dataclasses import replace

        from cli.commands.tasks_lifecycle import _cleanup_safe_pause_residue

        meta, load, _, remove, _, _, _, _ = safe_checkpoint
        load.side_effect = [meta, replace(meta, created_at="2026-10-03T02:01:00Z")]
        assert _cleanup_safe_pause_residue("task-123", "summitflow") == "checkpoint_kept:checkpoint_changed"
        remove.assert_not_called()

    def test_diagnostic_error_does_not_undo_pause(self, safe_checkpoint) -> None:
        from cli.commands.tasks_lifecycle import _cleanup_safe_pause_residue

        _, _, _, remove, _, task, _, _ = safe_checkpoint
        task.side_effect = RuntimeError("sensitive diagnostic detail")
        assert _cleanup_safe_pause_residue("task-123", "summitflow") == "checkpoint_kept:inspection_unavailable"
        remove.assert_not_called()

    def test_ref_inspection_error_is_preserved(self, safe_checkpoint) -> None:
        from cli.commands.tasks_lifecycle import _cleanup_safe_pause_residue

        _, _, _, remove, _, _, git, _ = safe_checkpoint
        git.side_effect = [MagicMock(returncode=0, stdout=""), MagicMock(returncode=1, stdout="")]
        assert _cleanup_safe_pause_residue("task-123", "summitflow") == "checkpoint_kept:inspection_unavailable"
        remove.assert_not_called()

    def test_missing_registered_root_is_preserved(self, safe_checkpoint) -> None:
        from cli.commands.tasks_lifecycle import _cleanup_safe_pause_residue

        _, _, _, remove, root, _, git, _ = safe_checkpoint
        root.return_value = None
        assert _cleanup_safe_pause_residue("task-123", "summitflow") == "checkpoint_kept:project_root_unavailable"
        remove.assert_not_called()
        git.assert_not_called()

    def test_foreign_task_status_is_preserved(self, safe_checkpoint) -> None:
        from cli.commands.tasks_lifecycle import _cleanup_safe_pause_residue

        _, _, _, remove, _, task, _, _ = safe_checkpoint
        task.return_value["project_id"] = "other"
        assert _cleanup_safe_pause_residue("task-123", "summitflow") == "checkpoint_kept:task_not_paused"
        remove.assert_not_called()


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
