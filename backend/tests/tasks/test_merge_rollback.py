"""Tests for autonomous merge operations."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# merge_and_cleanup_task_checkpoint (orchestrator)
# ---------------------------------------------------------------------------


class TestMergeAndCleanup:
    """Tests for the merge orchestrator."""

    @patch("app.tasks.autonomous.cleanup.merge_operations._git")
    @patch("app.tasks.autonomous.cleanup.merge_operations.publish_existing_commits")
    @patch("app.tasks.autonomous.cleanup.merge_operations.update_task_fields")
    @patch("app.tasks.autonomous.cleanup.merge_operations.delete_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.remove_task_checkout")
    @patch("app.tasks.autonomous.cleanup.merge_operations.merge_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.checkout_base_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_checkout")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_successful_merge_returns_merged(
        self,
        mock_store: MagicMock,
        mock_get_checkout: MagicMock,
        mock_root: MagicMock,
        mock_checkout_base: MagicMock,
        mock_merge: MagicMock,
        mock_remove: MagicMock,
        mock_delete: MagicMock,
        mock_fields: MagicMock,
        mock_publish: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_checkpoint,
        )

        mock_store.get_task.return_value = {"status": "completed"}
        wt = MagicMock()
        wt.branch = "task-1/main"
        wt.base_branch = "main"
        mock_get_checkout.return_value = wt
        mock_root.return_value = "/tmp/project"
        mock_checkout_base.return_value = None  # No error
        mock_merge.return_value = MagicMock(success=True, merge_sha="abc123", conflicting_files=None)
        mock_delete.return_value = True
        mock_publish.return_value = True
        mock_git.return_value = MagicMock(returncode=0, stdout="")

        result = cast(dict[str, object], merge_and_cleanup_task_checkpoint("task-1", "test-project"))

        assert result["status"] == "merged"
        assert result["post_merge_valid"]
        assert result["post_merge_validation_status"] == "skipped"
        mock_git.assert_any_call(
            ["git", "update-ref", "refs/summitflow/snapshots/pre-merge/task-1", "HEAD"],
            "/tmp/project",
        )

    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_checkout")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_running_task_blocked(
        self, mock_store: MagicMock, mock_checkout: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_checkpoint,
        )

        mock_store.get_task.return_value = {"status": "running"}

        result = cast(dict[str, object], merge_and_cleanup_task_checkpoint("task-1", "test-project"))

        assert result["status"] == "failed"
        assert result["reason"] == "task_still_running"

    @patch("app.tasks.autonomous.cleanup.merge_operations._git")
    @patch("app.tasks.autonomous.cleanup.merge_operations._clear_checkpoint_residue")
    @patch("app.tasks.autonomous.cleanup.merge_operations.delete_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.checkout_base_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_checkout")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_no_checkout_still_finalizes_safe_branch_cleanup(
        self,
        mock_store: MagicMock,
        mock_get_checkout: MagicMock,
        mock_root: MagicMock,
        mock_checkout_base: MagicMock,
        mock_delete: MagicMock,
        mock_clear_checkpoint: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_checkpoint,
        )

        mock_store.get_task.return_value = {"status": "completed", "branch_name": "task-1/main"}
        mock_get_checkout.return_value = None
        mock_root.return_value = "/tmp/project"
        mock_checkout_base.return_value = None
        mock_delete.return_value = True

        result = merge_and_cleanup_task_checkpoint("task-1", "test-project")

        assert result["status"] == "merged"
        assert result["branch_deleted"]
        mock_checkout_base.assert_called_once_with("/tmp/project", "main")
        mock_delete.assert_called_once_with("/tmp/project", "task-1/main", "task-1")
        mock_clear_checkpoint.assert_called_once_with("task-1", "test-project")

    @patch("app.tasks.autonomous.cleanup.merge_operations._clear_checkpoint_residue")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_checkout")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_no_checkout_without_project_root_still_clears_checkpoint_residue(
        self,
        mock_store: MagicMock,
        mock_checkout: MagicMock,
        mock_root: MagicMock,
        mock_clear_checkpoint: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_checkpoint,
        )

        mock_store.get_task.return_value = {"status": "completed", "branch_name": "task-1/main"}
        mock_checkout.return_value = None
        mock_root.return_value = None

        result = merge_and_cleanup_task_checkpoint("task-1", "test-project")

        assert result["status"] == "skipped"
        assert result["reason"] == "no_checkpoint"
        mock_clear_checkpoint.assert_called_once_with("task-1", "test-project")

    @patch("app.tasks.autonomous.cleanup.merge_operations._git")
    @patch("app.tasks.autonomous.cleanup.merge_operations.publish_existing_commits")
    @patch("app.tasks.autonomous.cleanup.merge_operations.update_task_fields")
    @patch("app.tasks.autonomous.cleanup.merge_operations.delete_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.remove_task_checkout")
    @patch("app.tasks.autonomous.cleanup.merge_operations.merge_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.checkout_base_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_checkout")
    @patch("app.tasks.autonomous.cleanup.merge_operations.update_task_status")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_successful_merge_from_blocked_task_forces_completed_transition(
        self,
        mock_store: MagicMock,
        mock_update_status: MagicMock,
        mock_get_checkout: MagicMock,
        mock_root: MagicMock,
        mock_checkout_base: MagicMock,
        mock_merge: MagicMock,
        mock_remove: MagicMock,
        mock_delete: MagicMock,
        mock_fields: MagicMock,
        mock_publish: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_checkpoint,
        )

        mock_store.get_task.return_value = {"status": "blocked"}
        wt = MagicMock()
        wt.branch = "task-1/main"
        wt.base_branch = "main"
        mock_get_checkout.return_value = wt
        mock_root.return_value = "/tmp/project"
        mock_checkout_base.return_value = None
        mock_merge.return_value = MagicMock(success=True, merge_sha="abc123", conflicting_files=None)
        mock_delete.return_value = True
        mock_publish.return_value = True
        mock_git.return_value = MagicMock(returncode=0, stdout="")

        result = merge_and_cleanup_task_checkpoint("task-1", "test-project")

        assert result["status"] == "merged"
        mock_update_status.assert_any_call("task-1", "completed", validate_transition=False)

    @patch("app.tasks.autonomous.cleanup.merge_operations._git")
    @patch("app.tasks.autonomous.cleanup.merge_operations.publish_existing_commits")
    @patch("app.tasks.autonomous.cleanup.merge_operations.update_task_fields")
    @patch("app.tasks.autonomous.cleanup.merge_operations.delete_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.remove_task_checkout")
    @patch("app.tasks.autonomous.cleanup.merge_operations.merge_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.checkout_base_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_checkout")
    @patch("app.tasks.autonomous.cleanup.merge_operations.update_task_status")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_publish_failure_keeps_checkout_and_marks_task_failed(
        self,
        mock_store: MagicMock,
        mock_update_status: MagicMock,
        mock_get_checkout: MagicMock,
        mock_root: MagicMock,
        mock_checkout_base: MagicMock,
        mock_merge: MagicMock,
        mock_remove: MagicMock,
        mock_delete: MagicMock,
        mock_fields: MagicMock,
        mock_publish: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_checkpoint,
        )

        mock_store.get_task.return_value = {"status": "completed"}
        wt = MagicMock()
        wt.branch = "task-1/main"
        wt.base_branch = "main"
        mock_get_checkout.return_value = wt
        mock_root.return_value = "/tmp/project"
        mock_checkout_base.return_value = None
        mock_merge.return_value = MagicMock(success=True, merge_sha="abc123", conflicting_files=None)
        mock_publish.return_value = False
        mock_git.return_value = MagicMock(returncode=0, stdout="")

        result = cast(dict[str, object], merge_and_cleanup_task_checkpoint("task-1", "test-project"))

        assert result["status"] == "error"
        assert "local-only" in str(result["error"])
        mock_remove.assert_not_called()
        mock_delete.assert_not_called()
        mock_update_status.assert_any_call(
            "task-1",
            "failed",
            error_message="Auto-merge result not published; main still local-only",
            validate_transition=False,
        )
