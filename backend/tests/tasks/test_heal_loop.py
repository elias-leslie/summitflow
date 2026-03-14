"""Tests for autocode heal loop bug fixes.

Covers:
- Bug #1: Steps re-read from DB after heal attempts (st step defect picked up)
- Bug #2: Worktree race condition protection (merge blocked, health check)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Module path constants for patching
# ---------------------------------------------------------------------------
_RETRY_LOOP = "app.tasks.autonomous.exec_modules.retry_loop"
_WORKTREE = "app.tasks.autonomous.exec_modules.worktree"
_SUBTASK_VALIDATION = "app.tasks.autonomous.exec_modules.subtask_validation"
_CLEANUP = "app.tasks.autonomous.cleanup.merge_operations"


class TestStepRereadAfterHealAttempt:
    """Bug #1: Heal loop re-reads steps from DB on retry."""

    @patch(f"{_RETRY_LOOP}.agent_configs")
    @patch(f"{_RETRY_LOOP}.execute_fix_attempt")
    @patch(f"{_RETRY_LOOP}.determine_fix_prompt")
    @patch(f"{_RETRY_LOOP}.handle_infrastructure_failures")
    @patch(f"{_RETRY_LOOP}.check_and_request_extension")
    @patch(f"{_RETRY_LOOP}.run_execution_quality_check")
    @patch(f"{_RETRY_LOOP}.check_worktree_health")
    @patch(f"{_RETRY_LOOP}.get_steps_for_subtask")
    @patch(f"{_RETRY_LOOP}.assert_task_runnable")
    def test_steps_reread_after_heal_attempt(
        self,
        mock_assert_task_runnable: MagicMock,
        mock_get_steps: MagicMock,
        mock_worktree_health: MagicMock,
        mock_verify: MagicMock,
        mock_extension: MagicMock,
        mock_infra: MagicMock,
        mock_fix_prompt: MagicMock,
        mock_fix_attempt: MagicMock,
        mock_agent_configs: MagicMock,
    ) -> None:
        """get_steps_for_subtask is called on heal attempts > 0."""
        from app.tasks.autonomous.exec_modules.retry_loop import run_self_healing_loop

        # agent_configs returns 0 so constants are used as fallback
        mock_agent_configs.get_max_self_fix_attempts.return_value = 0
        mock_agent_configs.get_max_supervisor_attempts.return_value = 0

        mock_worktree_health.return_value = True

        updated_steps = [
            {"step_number": 1, "description": "test", "status": "plan_defect"},
            {"step_number": 2, "description": "fix step"},
        ]
        mock_get_steps.return_value = updated_steps

        # First verify: fail, second verify (after re-read): pass
        mock_verify.side_effect = [
            (False, [{"step_number": 1, "passed": False, "output": "error", "reason": "failed", "returncode": 1}]),
            (True, [{"step_number": 1, "passed": True, "output": "ok", "reason": "", "returncode": 0}]),
        ]

        # No infrastructure failures
        mock_infra.side_effect = lambda failed, *a: failed

        mock_fix_prompt.return_value = ("fix prompt", None)
        mock_fix_attempt.return_value = ("fixed", "session-2")

        original_steps = [{"step_number": 1, "description": "test"}]

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
        }

        result = run_self_healing_loop(
            task_id="task-1",
            subtask_id="sub-1",
            subtask_short_id="1.1",
            subtask=subtask,
            steps=original_steps,
            project_path="/tmp/test-worktree",
            project_id="test-project",
            agent_slug="coder",
            agent_session_id="session-1",
            initial_response_content="initial",
        )

        all_passed = result[0]
        assert all_passed
        mock_get_steps.assert_called_once_with("sub-1")

    @patch(f"{_RETRY_LOOP}.agent_configs")
    @patch(f"{_RETRY_LOOP}.run_execution_quality_check")
    @patch(f"{_RETRY_LOOP}.check_worktree_health")
    @patch(f"{_RETRY_LOOP}.get_steps_for_subtask")
    @patch(f"{_RETRY_LOOP}.assert_task_runnable")
    def test_steps_not_reread_on_first_attempt(
        self,
        mock_assert_task_runnable: MagicMock,
        mock_get_steps: MagicMock,
        mock_worktree_health: MagicMock,
        mock_verify: MagicMock,
        mock_agent_configs: MagicMock,
    ) -> None:
        """get_steps_for_subtask is NOT called on first attempt (uses caller data)."""
        from app.tasks.autonomous.exec_modules.retry_loop import run_self_healing_loop

        mock_agent_configs.get_max_self_fix_attempts.return_value = 0
        mock_agent_configs.get_max_supervisor_attempts.return_value = 0

        mock_worktree_health.return_value = True

        # All steps pass on first attempt
        mock_verify.return_value = (
            True,
            [{"step_number": 1, "passed": True, "output": "ok", "reason": "", "returncode": 0}],
        )

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
        }

        result = run_self_healing_loop(
            task_id="task-1",
            subtask_id="sub-1",
            subtask_short_id="1.1",
            subtask=subtask,
            steps=[{"step_number": 1, "description": "test"}],
            project_path="/tmp/test-worktree",
            project_id="test-project",
            agent_slug="coder",
            agent_session_id="session-1",
            initial_response_content="initial",
        )

        all_passed = result[0]
        assert all_passed
        mock_get_steps.assert_not_called()


class TestMergeBlockedWhenTaskRunning:
    """Bug #2, Layer A: Merge operations blocked when task is running."""

    @patch(f"{_CLEANUP}.get_project_root_path")
    @patch(f"{_CLEANUP}.get_task_worktree")
    @patch(f"{_CLEANUP}.task_store")
    def test_merge_blocked_when_task_running(
        self,
        mock_store: MagicMock,
        mock_worktree: MagicMock,
        mock_root: MagicMock,
    ) -> None:
        """merge_and_cleanup_task_worktree returns blocked when status=running."""
        from app.tasks.autonomous.cleanup import merge_and_cleanup_task_worktree

        mock_store.get_task.return_value = {"id": "task-1", "status": "running"}

        result = merge_and_cleanup_task_worktree("task-1", "test-project")

        assert result["status"] == "blocked"
        assert result["reason"] == "task_still_running"
        mock_worktree.assert_not_called()

    @patch(f"{_CLEANUP}._git")
    @patch(f"{_CLEANUP}.update_task_fields")
    @patch(f"{_CLEANUP}.run_post_merge_validation")
    @patch(f"{_CLEANUP}.delete_task_branch")
    @patch(f"{_CLEANUP}.merge_task_branch")
    @patch(f"{_CLEANUP}.checkout_base_branch")
    @patch(f"{_CLEANUP}.get_project_root_path")
    @patch(f"{_CLEANUP}.remove_task_worktree")
    @patch(f"{_CLEANUP}.get_task_worktree")
    @patch(f"{_CLEANUP}.task_store")
    def test_merge_allowed_when_task_completed(
        self,
        mock_store: MagicMock,
        mock_worktree: MagicMock,
        mock_remove: MagicMock,
        mock_root: MagicMock,
        mock_checkout: MagicMock,
        mock_merge: MagicMock,
        mock_delete_branch: MagicMock,
        mock_validation: MagicMock,
        mock_fields: MagicMock,
        mock_git: MagicMock,
    ) -> None:
        """merge_and_cleanup_task_worktree proceeds when status != running."""
        from app.tasks.autonomous.cleanup import merge_and_cleanup_task_worktree

        mock_store.get_task.return_value = {"id": "task-1", "status": "completed"}

        worktree_obj = MagicMock()
        worktree_obj.branch = "task-1/main"
        worktree_obj.base_branch = "main"
        mock_worktree.return_value = worktree_obj

        mock_root.return_value = "/home/test/project"

        # All git operations succeed
        mock_checkout.return_value = None
        mock_merge.return_value = MagicMock(success=True, merge_sha="abc123", conflicting_files=None)
        mock_delete_branch.return_value = True
        mock_validation.return_value = True
        mock_git.return_value = MagicMock(returncode=0, stdout="")

        result = merge_and_cleanup_task_worktree("task-1", "test-project")

        assert result["status"] == "merged"


class TestWorktreeHealthCheck:
    """Bug #2, Layer B: Worktree health check function."""

    @patch(f"{_WORKTREE}.emit_log")
    def test_worktree_health_check_missing_dir(
        self,
        mock_log: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Returns False and logs error when directory doesn't exist."""
        from app.tasks.autonomous.exec_modules.worktree import check_worktree_health

        missing = str(tmp_path / "nonexistent")
        result = check_worktree_health(missing, "task-1", "test-project")

        assert not result
        mock_log.assert_called_once()
        assert "WORKTREE GONE" in mock_log.call_args[0][2]

    @patch(f"{_WORKTREE}.emit_log")
    def test_worktree_health_check_no_git_marker(
        self,
        mock_log: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Returns False when directory exists but has no .git marker."""
        from app.tasks.autonomous.exec_modules.worktree import check_worktree_health

        result = check_worktree_health(str(tmp_path), "task-1", "test-project")

        assert not result
        mock_log.assert_called_once()
        assert "WORKTREE CORRUPTED" in mock_log.call_args[0][2]

    @patch(f"{_WORKTREE}.emit_log")
    def test_worktree_health_check_valid(
        self,
        mock_log: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Returns True for a valid worktree directory with .git marker."""
        from app.tasks.autonomous.exec_modules.worktree import check_worktree_health

        (tmp_path / ".git").mkdir()
        result = check_worktree_health(str(tmp_path), "task-1", "test-project")

        assert result
        mock_log.assert_not_called()

    @patch(f"{_WORKTREE}.emit_log")
    def test_worktree_health_check_valid_git_file(
        self,
        mock_log: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Returns True when .git is a file (worktree gitlink)."""
        from app.tasks.autonomous.exec_modules.worktree import check_worktree_health

        (tmp_path / ".git").write_text("gitdir: /path/to/main/.git/worktrees/task-1")
        result = check_worktree_health(str(tmp_path), "task-1", "test-project")

        assert result
        mock_log.assert_not_called()


class TestHealLoopAbortsOnInvalidWorktree:
    """Bug #2, Layer B: Heal loop breaks immediately on worktree destruction."""

    @patch(f"{_RETRY_LOOP}.agent_configs")
    @patch(f"{_RETRY_LOOP}.run_execution_quality_check")
    @patch(f"{_RETRY_LOOP}.check_worktree_health")
    @patch(f"{_RETRY_LOOP}.get_steps_for_subtask")
    @patch(f"{_RETRY_LOOP}.assert_task_runnable")
    def test_heal_loop_aborts_on_invalid_worktree(
        self,
        mock_assert_task_runnable: MagicMock,
        mock_get_steps: MagicMock,
        mock_worktree_health: MagicMock,
        mock_verify: MagicMock,
        mock_agent_configs: MagicMock,
    ) -> None:
        """Subtask fails immediately when worktree is destroyed."""
        from app.tasks.autonomous.exec_modules.retry_loop import run_self_healing_loop

        mock_agent_configs.get_max_self_fix_attempts.return_value = 0
        mock_agent_configs.get_max_supervisor_attempts.return_value = 0

        # Worktree check fails on first iteration (heal_attempt=0)
        mock_worktree_health.return_value = False

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
        }

        result = run_self_healing_loop(
            task_id="task-1",
            subtask_id="sub-1",
            subtask_short_id="1.1",
            subtask=subtask,
            steps=[{"step_number": 1, "description": "test"}],
            project_path="/tmp/test-worktree",
            project_id="test-project",
            agent_slug="coder",
            agent_session_id="session-1",
            initial_response_content="done",
        )

        all_passed = result[0]
        step_results = result[1]
        assert not all_passed
        assert step_results[0]["reason"] == "worktree_destroyed"


class TestInitialWorktreeGuard:
    """Bug #2, Layer C: Initial worktree check before agent call."""

    @patch(f"{_SUBTASK_VALIDATION}.emit_log")
    @patch(f"{_SUBTASK_VALIDATION}.check_worktree_health")
    def test_execute_subtask_fails_on_invalid_worktree(
        self,
        mock_worktree_health: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """validate_subtask_environment returns failed when worktree is invalid at start."""
        from app.tasks.autonomous.exec_modules.subtask_validation import (
            validate_subtask_environment,
        )

        mock_worktree_health.return_value = False

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
            "steps_from_table": [],
        }

        result = validate_subtask_environment(
            "task-1", subtask, "1.1", "/tmp/nonexistent", "test-project"
        )

        assert result is not None
        assert result["status"] == "failed"
        assert result["reason"] == "worktree_invalid"


class TestMainRepoLeakageDetection:
    """Detect when agent writes files to main repo instead of worktree."""

    @patch(f"{_WORKTREE}._load_main_repo_dirty_baseline")
    @patch(f"{_WORKTREE}.emit_log")
    @patch(f"{_WORKTREE}.subprocess")
    @patch(f"{_WORKTREE}.get_project_root_path")
    def test_leakage_detected_when_main_repo_dirty(
        self,
        mock_root: MagicMock,
        mock_subprocess: MagicMock,
        mock_log: MagicMock,
        mock_baseline: MagicMock,
    ) -> None:
        """Returns True and logs warning when main repo has uncommitted changes."""
        from app.tasks.autonomous.exec_modules.worktree import check_main_repo_leakage

        mock_root.return_value = "/home/test/project"
        mock_baseline.return_value = []
        result_obj = MagicMock()
        result_obj.stdout = " M leaked_file.py\n"
        mock_subprocess.run.return_value = result_obj

        detected = check_main_repo_leakage("task-1", "test-project", "/tmp/worktree")

        assert detected
        assert any("WORKTREE LEAKAGE" in str(c) for c in mock_log.call_args_list)

    @patch(f"{_WORKTREE}._load_main_repo_dirty_baseline")
    @patch(f"{_WORKTREE}.emit_log")
    @patch(f"{_WORKTREE}.subprocess")
    @patch(f"{_WORKTREE}.get_project_root_path")
    def test_no_leakage_when_only_preexisting_dirty_files_remain(
        self,
        mock_root: MagicMock,
        mock_subprocess: MagicMock,
        mock_log: MagicMock,
        mock_baseline: MagicMock,
    ) -> None:
        """Returns False when current dirt matches the recorded baseline."""
        from app.tasks.autonomous.exec_modules.worktree import check_main_repo_leakage

        mock_root.return_value = "/home/test/project"
        mock_baseline.return_value = ["existing_file.py"]
        result_obj = MagicMock()
        result_obj.stdout = " M existing_file.py\n"
        mock_subprocess.run.return_value = result_obj

        detected = check_main_repo_leakage("task-1", "test-project", "/tmp/worktree")

        assert not detected
        mock_log.assert_not_called()

    @patch(f"{_WORKTREE}._load_main_repo_dirty_baseline")
    @patch(f"{_WORKTREE}.emit_log")
    @patch(f"{_WORKTREE}.subprocess")
    @patch(f"{_WORKTREE}.get_project_root_path")
    def test_leakage_detected_when_new_dirty_file_added_beyond_baseline(
        self,
        mock_root: MagicMock,
        mock_subprocess: MagicMock,
        mock_log: MagicMock,
        mock_baseline: MagicMock,
    ) -> None:
        """Returns True when execution dirt exceeds the recorded baseline."""
        from app.tasks.autonomous.exec_modules.worktree import check_main_repo_leakage

        mock_root.return_value = "/home/test/project"
        mock_baseline.return_value = ["existing_file.py"]
        result_obj = MagicMock()
        result_obj.stdout = " M existing_file.py\n M leaked_file.py\n"
        mock_subprocess.run.return_value = result_obj

        detected = check_main_repo_leakage("task-1", "test-project", "/tmp/worktree")

        assert detected
        assert any("leaked_file.py" in str(c) for c in mock_log.call_args_list)

    @patch(f"{_WORKTREE}.emit_log")
    @patch(f"{_WORKTREE}.subprocess")
    @patch(f"{_WORKTREE}.get_project_root_path")
    def test_no_leakage_when_main_repo_clean(
        self,
        mock_root: MagicMock,
        mock_subprocess: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Returns False when main repo is clean."""
        from app.tasks.autonomous.exec_modules.worktree import check_main_repo_leakage

        mock_root.return_value = "/home/test/project"
        result_obj = MagicMock()
        result_obj.stdout = ""
        mock_subprocess.run.return_value = result_obj

        detected = check_main_repo_leakage("task-1", "test-project", "/tmp/worktree")

        assert not detected

    @patch(f"{_WORKTREE}.emit_log")
    @patch(f"{_WORKTREE}.get_project_root_path")
    def test_skipped_when_same_path(
        self,
        mock_root: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Returns False immediately when project_path equals main root."""
        from app.tasks.autonomous.exec_modules.worktree import check_main_repo_leakage

        mock_root.return_value = "/home/test/project"

        detected = check_main_repo_leakage("task-1", "test-project", "/home/test/project")

        assert not detected
        mock_log.assert_not_called()


class TestZeroStepSubtask:
    """Zero-step subtask logs a warning but does not fail — uses smoke tests only."""

    @patch(f"{_SUBTASK_VALIDATION}.emit_log")
    @patch(f"{_SUBTASK_VALIDATION}.check_worktree_health")
    def test_zero_steps_returns_none(
        self,
        mock_worktree_health: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Subtask with 0 steps returns None (passes env check) and logs an info message."""
        from app.tasks.autonomous.exec_modules.subtask_validation import (
            validate_subtask_environment,
        )

        mock_worktree_health.return_value = True

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "empty subtask",
            "steps_from_table": [],
        }

        result = validate_subtask_environment(
            "task-1", subtask, "1.1", "/tmp/test-worktree", "test-project"
        )

        # Zero steps is now valid — execution proceeds with smoke tests only
        assert result is None


class TestWorkProductDetection:
    """Verification should treat dirty worktree edits as valid work product."""

    @patch("app.tasks.autonomous.exec_modules.steps.subprocess.run")
    def test_has_work_product_when_branch_has_commits(self, mock_run: MagicMock) -> None:
        """A branch commit beyond main counts as work product."""
        from app.tasks.autonomous.exec_modules.steps import _has_work_product

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),  # detect base branch
            MagicMock(returncode=0, stdout="abc123 change\n"),  # git log main..HEAD
        ]

        assert _has_work_product("/tmp/test-worktree")

    @patch("app.tasks.autonomous.exec_modules.steps.subprocess.run")
    def test_has_work_product_when_worktree_has_uncommitted_changes(
        self,
        mock_run: MagicMock,
    ) -> None:
        """Dirty worktree edits should count even before a commit exists."""
        from app.tasks.autonomous.exec_modules.steps import _has_work_product

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),  # detect base branch
            MagicMock(returncode=0, stdout=""),  # git log (no commits)
            MagicMock(stdout=" M terminal/api/handlers/websocket_resize.py\n"),  # git status
        ]

        assert _has_work_product("/tmp/test-worktree")

    @patch("app.tasks.autonomous.exec_modules.steps.subprocess.run")
    def test_has_work_product_detects_master_branch(self, mock_run: MagicMock) -> None:
        """Repos using 'master' as default branch should be detected."""
        from app.tasks.autonomous.exec_modules.steps import _has_work_product

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/master\n"),  # detect master
            MagicMock(returncode=0, stdout="abc123 fix\n"),  # git log master..HEAD
        ]

        assert _has_work_product("/tmp/test-worktree")
        # Verify git log used "master" not "main"
        log_call = mock_run.call_args_list[1]
        assert "master..HEAD" in log_call[0][0]

    @patch("app.tasks.autonomous.exec_modules.git_work_product.emit_log")
    @patch("app.tasks.autonomous.exec_modules.git_work_product.has_unpublished_commits")
    @patch("app.tasks.autonomous.exec_modules.git_work_product.smart_commit")
    @patch("app.tasks.autonomous.exec_modules.git_work_product.has_uncommitted_changes")
    @patch("app.tasks.autonomous.exec_modules.git_work_product._has_branch_commits")
    def test_ensure_committed_work_product_commits_dirty_changes(
        self,
        mock_has_branch_commits: MagicMock,
        mock_has_uncommitted_changes: MagicMock,
        mock_smart_commit: MagicMock,
        mock_has_unpublished_commits: MagicMock,
        mock_emit_log: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.git_work_product import ensure_committed_work_product

        mock_has_branch_commits.side_effect = [False, True]
        mock_has_uncommitted_changes.return_value = True
        mock_smart_commit.return_value = True
        mock_has_unpublished_commits.return_value = False

        result = ensure_committed_work_product("task-1", "1.1", "/tmp/test-worktree", "agent-hub")

        assert result is None
        mock_emit_log.assert_called_once()
        mock_smart_commit.assert_called_once_with(
            "/tmp/test-worktree",
            "autocode(task-1): complete subtask 1.1",
            task_id="task-1",
            push=True,
        )

    @patch("app.tasks.autonomous.exec_modules.git_work_product.publish_existing_commits")
    @patch("app.tasks.autonomous.exec_modules.git_work_product._has_branch_commits")
    def test_ensure_committed_work_product_publishes_existing_branch_commits(
        self,
        mock_has_branch_commits: MagicMock,
        mock_publish_existing_commits: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.git_work_product import ensure_committed_work_product

        mock_has_branch_commits.return_value = True
        mock_publish_existing_commits.return_value = True

        result = ensure_committed_work_product("task-1", "1.1", "/tmp/test-worktree", "agent-hub")

        assert result is None
        mock_publish_existing_commits.assert_called_once_with("/tmp/test-worktree")

    @patch("app.tasks.autonomous.exec_modules.git_work_product.subprocess.run")
    def test_ensure_committed_work_product_fails_when_nothing_to_merge(
        self,
        mock_run: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.git_work_product import ensure_committed_work_product

        mock_run.side_effect = [
            MagicMock(stdout="", returncode=0),  # git log main..HEAD
            MagicMock(stdout="", returncode=0),  # git status --porcelain
        ]

        result = ensure_committed_work_product("task-1", "1.1", "/tmp/test-worktree", "agent-hub")

        assert result == "No committed or dirty work product remains to merge"

    @patch("app.tasks.autonomous.exec_modules.steps.subprocess.run")
    def test_has_no_work_product_when_branch_clean_and_no_commits(
        self,
        mock_run: MagicMock,
    ) -> None:
        """No branch commits and no dirty files means nothing was produced."""
        from app.tasks.autonomous.exec_modules.steps import _has_work_product

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),  # detect base branch
            MagicMock(returncode=0, stdout=""),  # git log (no commits)
            MagicMock(stdout=""),  # git status (clean)
        ]

        assert not _has_work_product("/tmp/test-worktree")

    @patch("app.tasks.autonomous.exec_modules.steps.run_smoke_and_targeted_tests")
    @patch("app.tasks.autonomous.exec_modules.steps.get_task_spirit")
    @patch("app.tasks.autonomous.exec_modules.steps.get_task")
    @patch("app.tasks.autonomous.exec_modules.steps.subprocess.run")
    def test_run_execution_quality_check_allows_no_code_validation_tasks(
        self,
        mock_run: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_smoke: MagicMock,
    ) -> None:
        """Explicit workflow-only validation tasks should not fail on missing commits."""
        from app.tasks.autonomous.exec_modules.steps import run_execution_quality_check

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),  # detect base branch
            MagicMock(returncode=0, stdout=""),  # git log (no commits)
            MagicMock(stdout=""),  # git status (clean)
        ]
        mock_get_task.return_value = {
            "id": "task-1",
            "title": "Workflow validation task",
            "description": "Do not modify product code during this workflow validation run.",
        }
        mock_get_spirit.return_value = {
            "objective": "Run a workflow-only validation task.",
            "constraints": ["Do not require product code edits as part of the task outcome"],
        }
        mock_smoke.return_value = True

        all_passed, results = run_execution_quality_check(
            "task-1",
            "sub-1",
            [{"step_number": 1, "description": "Validate workflow", "passes": False}],
            "/tmp/test-worktree",
            "summitflow",
        )

        assert all_passed
        assert results[0]["passed"]
        assert results[0]["reason"] == "auto_passed"
        mock_smoke.assert_called_once()
