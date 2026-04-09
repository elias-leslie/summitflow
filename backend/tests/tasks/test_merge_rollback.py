"""Tests for merge operations, post-merge validation, and auto-rollback."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from app.tasks.autonomous.cleanup.validation import (
    auto_rollback,
    create_regression_fix_task,
    run_post_merge_validation,
    save_rollback_learning,
)

# ---------------------------------------------------------------------------
# run_post_merge_validation
# ---------------------------------------------------------------------------


class TestPostMergeValidation:
    """Tests for post-merge quality checks."""

    @patch("app.tasks.autonomous.cleanup.validation.build_dt_command")
    @patch("app.tasks.autonomous.cleanup.validation.find_dev_tools")
    @patch("app.storage.log_task_event")
    @patch("subprocess.run")
    def test_passes_when_dt_succeeds(
        self,
        mock_run: MagicMock,
        mock_log: MagicMock,
        mock_find_dt: MagicMock,
        mock_build_cmd: MagicMock,
    ) -> None:
        mock_find_dt.return_value = "/mock/dt"
        mock_build_cmd.return_value = ["/mock/dt", "--quick"]
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")

        result = run_post_merge_validation("task-1", "/tmp/project", "test-project")

        assert result == {
            "status": "passed",
            "passed": True,
            "should_rollback": False,
            "detail": None,
        }
        mock_run.assert_called_once_with(
            ["/mock/dt", "--quick"],
            cwd="/tmp/project",
            capture_output=True,
            text=True,
            timeout=120,
        )

    @patch("app.tasks.autonomous.cleanup.validation.find_dev_tools")
    @patch("app.storage.log_task_event")
    @patch("subprocess.run")
    def test_skips_when_dt_is_unavailable(
        self,
        mock_run: MagicMock,
        mock_log: MagicMock,
        mock_find_dt: MagicMock,
    ) -> None:
        mock_find_dt.return_value = None

        result = run_post_merge_validation("task-1", "/tmp/project", "test-project")

        assert result == {
            "status": "skipped",
            "passed": True,
            "should_rollback": False,
            "detail": "dt not available",
        }
        mock_run.assert_not_called()
        mock_log.assert_called_once_with("task-1", "Post-merge validation: SKIPPED - dt not available")

    @patch("app.tasks.autonomous.cleanup.validation.build_dt_command")
    @patch("app.tasks.autonomous.cleanup.validation.find_dev_tools")
    @patch("app.storage.log_task_event")
    @patch("subprocess.run")
    def test_fails_when_dt_fails(
        self,
        mock_run: MagicMock,
        mock_log: MagicMock,
        mock_find_dt: MagicMock,
        mock_build_cmd: MagicMock,
    ) -> None:
        mock_find_dt.return_value = "/mock/dt"
        mock_build_cmd.return_value = ["/mock/dt", "--quick"]
        mock_run.return_value = MagicMock(returncode=1, stdout="FAIL", stderr="error")

        result = run_post_merge_validation("task-1", "/tmp/project", "test-project")

        assert result["status"] == "failed"
        assert result["passed"] is False
        assert result["should_rollback"] is True
        mock_log.assert_called()

    @patch("app.tasks.autonomous.cleanup.validation.build_dt_command")
    @patch("app.tasks.autonomous.cleanup.validation.find_dev_tools")
    @patch("app.storage.log_task_event")
    @patch("subprocess.run")
    def test_fails_on_timeout(
        self,
        mock_run: MagicMock,
        mock_log: MagicMock,
        mock_find_dt: MagicMock,
        mock_build_cmd: MagicMock,
    ) -> None:
        mock_find_dt.return_value = "/mock/dt"
        mock_build_cmd.return_value = ["/mock/dt", "--quick"]
        mock_run.side_effect = subprocess.TimeoutExpired("dt", 120)

        result = run_post_merge_validation("task-1", "/tmp/project", "test-project")

        assert result == {
            "status": "timed_out",
            "passed": False,
            "should_rollback": False,
            "detail": "validation timed out after 120s",
        }

    @patch("app.tasks.autonomous.cleanup.validation.build_dt_command")
    @patch("app.tasks.autonomous.cleanup.validation.find_dev_tools")
    @patch("app.storage.log_task_event")
    @patch("subprocess.run")
    def test_skips_when_resolved_dt_disappears(
        self,
        mock_run: MagicMock,
        mock_log: MagicMock,
        mock_find_dt: MagicMock,
        mock_build_cmd: MagicMock,
    ) -> None:
        mock_find_dt.return_value = "/mock/dt"
        mock_build_cmd.return_value = ["/mock/dt", "--quick"]
        mock_run.side_effect = FileNotFoundError("dt not found")

        result = run_post_merge_validation("task-1", "/tmp/project", "test-project")

        assert result["status"] == "skipped"
        assert result["passed"] is True
        assert result["should_rollback"] is False
        mock_log.assert_called_once()


# ---------------------------------------------------------------------------
# auto_rollback
# ---------------------------------------------------------------------------


class TestAutoRollback:
    """Tests for auto-rollback after failed post-merge validation."""

    @patch("app.tasks.autonomous.cleanup.validation.save_rollback_learning")
    @patch("app.tasks.autonomous.cleanup.validation.create_regression_fix_task")
    @patch("app.tasks.autonomous.cleanup.validation.task_store")
    @patch("app.storage.log_task_event")
    @patch("app.tasks.autonomous.cleanup.validation._get_merge_affected_files")
    @patch("app.tasks.autonomous.cleanup.validation._get_head_commit")
    @patch("app.tasks.autonomous.cleanup.validation.revert_merge_commit")
    def test_successful_rollback(
        self, mock_revert: MagicMock, mock_head: MagicMock, mock_files: MagicMock,
        mock_log: MagicMock, mock_store: MagicMock, mock_create: MagicMock, mock_learn: MagicMock,
    ) -> None:
        mock_revert.return_value = True
        mock_head.return_value = "abc1234"
        mock_files.return_value = ["src/foo.py"]

        result = auto_rollback("task-1", "/tmp/project", "test-project", "task-1/main")

        assert result
        mock_revert.assert_called_once_with("task-1", "/tmp/project")
        mock_create.assert_called_once_with(
            "task-1", "test-project", "task-1/main",
            failure_detail=None,
            merge_commit="abc1234",
            affected_files=["src/foo.py"],
        )
        mock_store.update_task_status.assert_called_once_with("task-1", "failed")
        mock_learn.assert_called_once()

    @patch("app.tasks.autonomous.cleanup.validation.save_rollback_learning")
    @patch("app.tasks.autonomous.cleanup.validation.create_regression_fix_task")
    @patch("app.tasks.autonomous.cleanup.validation.task_store")
    @patch("app.storage.log_task_event")
    @patch("app.tasks.autonomous.cleanup.validation._get_merge_affected_files")
    @patch("app.tasks.autonomous.cleanup.validation._get_head_commit")
    @patch("app.tasks.autonomous.cleanup.validation.revert_merge_commit")
    def test_successful_rollback_from_completed_forces_failed_transition(
        self,
        mock_revert: MagicMock,
        mock_head: MagicMock,
        mock_files: MagicMock,
        mock_log: MagicMock,
        mock_store: MagicMock,
        mock_create: MagicMock,
        mock_learn: MagicMock,
    ) -> None:
        mock_revert.return_value = True
        mock_head.return_value = "abc1234"
        mock_files.return_value = []
        mock_store.get_task.return_value = {"status": "completed"}

        result = auto_rollback("task-1", "/tmp/project", "test-project", "task-1/main")

        assert result
        mock_store.update_task_status.assert_called_once_with(
            "task-1",
            "failed",
            validate_transition=False,
        )

    @patch("app.storage.log_task_event")
    @patch("app.tasks.autonomous.cleanup.validation.revert_merge_commit")
    def test_failed_revert_returns_false(
        self, mock_revert: MagicMock, mock_log: MagicMock,
    ) -> None:
        mock_revert.return_value = False

        result = auto_rollback("task-1", "/tmp/project", "test-project", "task-1/main")

        assert not result

    @patch("app.storage.log_task_event")
    @patch("app.tasks.autonomous.cleanup.validation.revert_merge_commit")
    def test_exception_returns_false(
        self, mock_revert: MagicMock, mock_log: MagicMock,
    ) -> None:
        mock_revert.side_effect = RuntimeError("git error")

        result = auto_rollback("task-1", "/tmp/project", "test-project", "task-1/main")

        assert not result

    @patch("app.storage.log_task_event")
    @patch("app.tasks.autonomous.cleanup.validation.revert_merge_commit")
    def test_timeout_returns_false(
        self, mock_revert: MagicMock, mock_log: MagicMock,
    ) -> None:
        mock_revert.side_effect = subprocess.TimeoutExpired("git", 30)

        result = auto_rollback("task-1", "/tmp/project", "test-project", "task-1/main")

        assert not result


# ---------------------------------------------------------------------------
# create_regression_fix_task
# ---------------------------------------------------------------------------


class TestCreateRegressionFixTask:
    """Tests for regression task creation after rollback."""

    @patch("app.tasks.autonomous.cleanup.validation._create_regression_subtasks")
    @patch("app.storage.task_spirit.update_task_spirit")
    @patch("app.storage.tasks.core.create_task")
    def test_creates_task_with_correct_fields(
        self, mock_create: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock,
    ) -> None:
        mock_create.return_value = {"id": "task-new-1"}

        create_regression_fix_task("task-1", "test-project", "task-1/main")

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["project_id"] == "test-project"
        assert kwargs["task_type"] == "regression"
        assert kwargs["priority"] == 1
        assert kwargs["parent_task_id"] == "task-1"
        assert kwargs["autonomous"]
        assert "task-1" in kwargs["title"]
        assert "task-1/main" in kwargs["title"]
        mock_spirit.assert_called_once_with("task-new-1", done_when=mock_spirit.call_args.kwargs["done_when"])
        assert len(mock_spirit.call_args.kwargs["done_when"]) == 3
        mock_subtasks.assert_called_once_with("task-new-1", "task-1/main", None)

    @patch("app.tasks.autonomous.cleanup.validation._create_regression_subtasks")
    @patch("app.storage.task_spirit.update_task_spirit")
    @patch("app.storage.tasks.core.create_task")
    def test_includes_failure_detail_and_commit_in_description(
        self, mock_create: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock,
    ) -> None:
        mock_create.return_value = {"id": "task-new-2"}

        create_regression_fix_task(
            "task-1", "test-project", "task-1/main",
            failure_detail="RUFF:FAIL\nsrc/foo.py: error",
            merge_commit="abc1234",
            affected_files=["src/foo.py", "src/bar.py"],
        )

        kwargs = mock_create.call_args.kwargs
        assert "abc1234" in kwargs["description"]
        assert "src/foo.py" in kwargs["description"]
        assert "RUFF:FAIL" in kwargs["description"]

    @patch("app.storage.tasks.core.create_task")
    def test_handles_creation_error_gracefully(self, mock_create: MagicMock) -> None:
        mock_create.side_effect = RuntimeError("DB error")

        # Should not raise
        create_regression_fix_task("task-1", "test-project", "task-1/main")


# ---------------------------------------------------------------------------
# save_rollback_learning
# ---------------------------------------------------------------------------


class TestSaveRollbackLearning:
    """Tests for saving rollback patterns to memory."""

    @patch("app.services.agent_hub_client.get_sync_client")
    def test_saves_learning_with_correct_params(self, mock_get: MagicMock) -> None:
        client = MagicMock()
        mock_get.return_value = client

        save_rollback_learning("task-1", "test-project", "task-1/main")

        client.save_learning.assert_called_once()
        call_kwargs = client.save_learning.call_args
        assert call_kwargs.kwargs["injection_tier"] == "guardrail"
        assert call_kwargs.kwargs["confidence"] == 85
        assert call_kwargs.kwargs["scope"] == "project"

    @patch("app.services.agent_hub_client.get_sync_client")
    def test_handles_error_silently(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = RuntimeError("connection failed")

        # Should not raise
        save_rollback_learning("task-1", "test-project", "task-1/main")


# ---------------------------------------------------------------------------
# merge_and_cleanup_task_worktree (orchestrator)
# ---------------------------------------------------------------------------


class TestMergeAndCleanup:
    """Tests for the merge orchestrator."""

    @patch("app.tasks.autonomous.cleanup.merge_operations._git")
    @patch("app.tasks.autonomous.cleanup.merge_operations.update_task_fields")
    @patch("app.tasks.autonomous.cleanup.merge_operations.run_post_merge_validation")
    @patch("app.tasks.autonomous.cleanup.merge_operations.delete_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.remove_task_worktree")
    @patch("app.tasks.autonomous.cleanup.merge_operations.merge_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.checkout_base_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_worktree")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_successful_merge_returns_merged(
        self,
        mock_store: MagicMock,
        mock_worktree: MagicMock,
        mock_root: MagicMock,
        mock_checkout: MagicMock,
        mock_merge: MagicMock,
        mock_remove: MagicMock,
        mock_delete: MagicMock,
        mock_validate: MagicMock,
        mock_fields: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_worktree,
        )

        mock_store.get_task.return_value = {"status": "completed"}
        wt = MagicMock()
        wt.branch = "task-1/main"
        wt.base_branch = "main"
        mock_worktree.return_value = wt
        mock_root.return_value = "/tmp/project"
        mock_checkout.return_value = None  # No error
        mock_merge.return_value = MagicMock(success=True, merge_sha="abc123", conflicting_files=None)
        mock_delete.return_value = True
        mock_validate.return_value = {
            "status": "passed",
            "passed": True,
            "should_rollback": False,
            "detail": None,
        }
        mock_git.return_value = MagicMock(returncode=0, stdout="")

        result = merge_and_cleanup_task_worktree("task-1", "test-project")

        assert result["status"] == "merged"
        assert result["post_merge_valid"]
        assert result["post_merge_validation_status"] == "passed"
        mock_git.assert_any_call(
            ["git", "update-ref", "refs/summitflow/snapshots/pre-merge/task-1", "HEAD"],
            "/tmp/project",
        )
        mock_git.assert_any_call(["git", "worktree", "prune"], "/tmp/project")

    @patch("app.tasks.autonomous.cleanup.merge_operations._git")
    @patch("app.tasks.autonomous.cleanup.merge_operations.update_task_fields")
    @patch("app.tasks.autonomous.cleanup.merge_operations.auto_rollback")
    @patch("app.tasks.autonomous.cleanup.merge_operations.run_post_merge_validation")
    @patch("app.tasks.autonomous.cleanup.merge_operations.delete_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.remove_task_worktree")
    @patch("app.tasks.autonomous.cleanup.merge_operations.merge_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.checkout_base_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_worktree")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_failed_validation_triggers_rollback(
        self,
        mock_store: MagicMock,
        mock_worktree: MagicMock,
        mock_root: MagicMock,
        mock_checkout: MagicMock,
        mock_merge: MagicMock,
        mock_remove: MagicMock,
        mock_delete: MagicMock,
        mock_validate: MagicMock,
        mock_rollback: MagicMock,
        mock_fields: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_worktree,
        )

        mock_store.get_task.return_value = {"status": "completed"}
        wt = MagicMock()
        wt.branch = "task-1/main"
        wt.base_branch = "main"
        mock_worktree.return_value = wt
        mock_root.return_value = "/tmp/project"
        mock_checkout.return_value = None
        mock_merge.return_value = MagicMock(success=True, merge_sha="abc123", conflicting_files=None)
        mock_delete.return_value = True
        mock_validate.return_value = {
            "status": "failed",
            "passed": False,
            "should_rollback": True,
            "detail": "FAIL",
        }
        mock_rollback.return_value = True
        mock_git.return_value = MagicMock(returncode=0, stdout="")

        result = merge_and_cleanup_task_worktree("task-1", "test-project")

        assert result["status"] == "rolled_back"
        assert result["reason"] == "post_merge_validation_failed"
        mock_rollback.assert_called_once()

    @patch("app.tasks.autonomous.cleanup.merge_operations._git")
    @patch("app.tasks.autonomous.cleanup.merge_operations.update_task_fields")
    @patch("app.tasks.autonomous.cleanup.merge_operations.auto_rollback")
    @patch("app.tasks.autonomous.cleanup.merge_operations.run_post_merge_validation")
    @patch("app.tasks.autonomous.cleanup.merge_operations.delete_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.remove_task_worktree")
    @patch("app.tasks.autonomous.cleanup.merge_operations.merge_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.checkout_base_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_worktree")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_timeout_validation_keeps_merge_and_skips_rollback(
        self,
        mock_store: MagicMock,
        mock_worktree: MagicMock,
        mock_root: MagicMock,
        mock_checkout: MagicMock,
        mock_merge: MagicMock,
        mock_remove: MagicMock,
        mock_delete: MagicMock,
        mock_validate: MagicMock,
        mock_rollback: MagicMock,
        mock_fields: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_worktree,
        )

        mock_store.get_task.return_value = {"status": "completed"}
        wt = MagicMock()
        wt.branch = "task-1/main"
        wt.base_branch = "main"
        mock_worktree.return_value = wt
        mock_root.return_value = "/tmp/project"
        mock_checkout.return_value = None
        mock_merge.return_value = MagicMock(success=True, merge_sha="abc123", conflicting_files=None)
        mock_delete.return_value = True
        mock_validate.return_value = {
            "status": "timed_out",
            "passed": False,
            "should_rollback": False,
            "detail": "validation timed out after 120s",
        }
        mock_git.return_value = MagicMock(returncode=0, stdout="")

        result = merge_and_cleanup_task_worktree("task-1", "test-project")

        assert result["status"] == "merged"
        assert result["post_merge_valid"] is False
        assert result["post_merge_validation_status"] == "timed_out"
        mock_rollback.assert_not_called()

    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_worktree")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_running_task_blocked(
        self, mock_store: MagicMock, mock_worktree: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_worktree,
        )

        mock_store.get_task.return_value = {"status": "running"}

        result = merge_and_cleanup_task_worktree("task-1", "test-project")

        assert result["status"] == "failed"
        assert result["reason"] == "task_still_running"

    @patch("app.tasks.autonomous.cleanup.merge_operations._git")
    @patch("app.tasks.autonomous.cleanup.merge_operations._clear_checkpoint_residue")
    @patch("app.tasks.autonomous.cleanup.merge_operations.delete_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.checkout_base_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_worktree")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_no_worktree_still_finalizes_safe_branch_cleanup(
        self,
        mock_store: MagicMock,
        mock_worktree: MagicMock,
        mock_root: MagicMock,
        mock_checkout: MagicMock,
        mock_delete: MagicMock,
        mock_clear_checkpoint: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_worktree,
        )

        mock_store.get_task.return_value = {"status": "completed", "branch_name": "task-1/main"}
        mock_worktree.return_value = None
        mock_root.return_value = "/tmp/project"
        mock_checkout.return_value = None
        mock_delete.return_value = True

        result = merge_and_cleanup_task_worktree("task-1", "test-project")

        assert result["status"] == "merged"
        assert result["branch_deleted"]
        mock_checkout.assert_called_once_with("/tmp/project", "main")
        mock_git.assert_called_once_with(["git", "worktree", "prune"], "/tmp/project")
        mock_delete.assert_called_once_with("/tmp/project", "task-1/main", "task-1")
        mock_clear_checkpoint.assert_called_once_with("task-1", "test-project")

    @patch("app.tasks.autonomous.cleanup.merge_operations._clear_checkpoint_residue")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_worktree")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_no_worktree_without_project_root_still_clears_checkpoint_residue(
        self,
        mock_store: MagicMock,
        mock_worktree: MagicMock,
        mock_root: MagicMock,
        mock_clear_checkpoint: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_worktree,
        )

        mock_store.get_task.return_value = {"status": "completed", "branch_name": "task-1/main"}
        mock_worktree.return_value = None
        mock_root.return_value = None

        result = merge_and_cleanup_task_worktree("task-1", "test-project")

        assert result["status"] == "skipped"
        assert result["reason"] == "no_worktree"
        mock_clear_checkpoint.assert_called_once_with("task-1", "test-project")

    @patch("app.tasks.autonomous.cleanup.merge_operations._git")
    @patch("app.tasks.autonomous.cleanup.merge_operations.update_task_fields")
    @patch("app.tasks.autonomous.cleanup.merge_operations.run_post_merge_validation")
    @patch("app.tasks.autonomous.cleanup.merge_operations.delete_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.remove_task_worktree")
    @patch("app.tasks.autonomous.cleanup.merge_operations.merge_task_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.checkout_base_branch")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.merge_operations.get_task_worktree")
    @patch("app.tasks.autonomous.cleanup.merge_operations.update_task_status")
    @patch("app.tasks.autonomous.cleanup.merge_operations.task_store")
    def test_successful_merge_from_blocked_task_forces_completed_transition(
        self,
        mock_store: MagicMock,
        mock_update_status: MagicMock,
        mock_worktree: MagicMock,
        mock_root: MagicMock,
        mock_checkout: MagicMock,
        mock_merge: MagicMock,
        mock_remove: MagicMock,
        mock_delete: MagicMock,
        mock_validate: MagicMock,
        mock_fields: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        from app.tasks.autonomous.cleanup.merge_operations import (
            merge_and_cleanup_task_worktree,
        )

        mock_store.get_task.return_value = {"status": "blocked"}
        wt = MagicMock()
        wt.branch = "task-1/main"
        wt.base_branch = "main"
        mock_worktree.return_value = wt
        mock_root.return_value = "/tmp/project"
        mock_checkout.return_value = None
        mock_merge.return_value = MagicMock(success=True, merge_sha="abc123", conflicting_files=None)
        mock_delete.return_value = True
        mock_validate.return_value = {
            "status": "passed",
            "passed": True,
            "should_rollback": False,
            "detail": None,
        }
        mock_git.return_value = MagicMock(returncode=0, stdout="")

        result = merge_and_cleanup_task_worktree("task-1", "test-project")

        assert result["status"] == "merged"
        mock_update_status.assert_any_call("task-1", "completed", validate_transition=False)
