"""Tests for autocode heal loop bug fixes.

Covers:
- Bug #1: Steps re-read from DB after heal attempts (st step defect picked up)
- Bug #2: Worktree race condition protection (merge blocked, health check)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


class TestStepRereadAfterHealAttempt:
    """Bug #1: Heal loop re-reads steps from DB on retry."""

    @patch("app.tasks.autonomous.execution._emit_log")
    @patch("app.tasks.autonomous.execution._emit_progress")
    @patch("app.tasks.autonomous.execution._emit_progress_log")
    @patch("app.tasks.autonomous.execution.run_smoke_tests")
    @patch("app.tasks.autonomous.execution.get_steps_for_subtask")
    @patch("app.tasks.autonomous.execution._verify_steps")
    @patch("app.tasks.autonomous.execution._build_fix_prompt")
    @patch("app.tasks.autonomous.execution._check_worktree_health")
    @patch("app.tasks.autonomous.execution._get_project_path")
    @patch("app.tasks.autonomous.execution._build_subtask_prompt")
    @patch("app.tasks.autonomous.execution.get_sync_client")
    @patch("app.tasks.autonomous.execution._has_uncommitted_changes")
    @patch("app.tasks.autonomous.execution._get_prompt_template")
    @patch("app.tasks.autonomous.execution.get_handoff_context")
    @patch("app.tasks.autonomous.execution.get_task_spirit")
    @patch("app.tasks.autonomous.execution.acknowledge_no_citations", create=True)
    def test_steps_reread_after_heal_attempt(
        self,
        mock_ack_citations: MagicMock,
        mock_spirit: MagicMock,
        mock_handoff: MagicMock,
        mock_template: MagicMock,
        mock_uncommitted: MagicMock,
        mock_client_factory: MagicMock,
        mock_build_prompt: MagicMock,
        mock_project_path: MagicMock,
        mock_worktree_health: MagicMock,
        mock_build_fix: MagicMock,
        mock_verify: MagicMock,
        mock_get_steps: MagicMock,
        mock_smoke: MagicMock,
        mock_progress_log: MagicMock,
        mock_progress: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """get_steps_for_subtask is called on heal attempts > 0."""
        from app.tasks.autonomous.execution import _execute_subtask

        mock_project_path.return_value = "/tmp/test-worktree"
        mock_worktree_health.return_value = True
        mock_build_prompt.return_value = "test prompt"
        mock_template.return_value = "fix {failures_block}"
        mock_build_fix.return_value = "fix prompt"
        mock_uncommitted.return_value = False
        mock_spirit.return_value = {"objective": "test", "spirit_anti": ""}
        mock_handoff.return_value = {}

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "fixed"
        mock_response.session_id = "session-1"
        mock_response.progress_log = []
        mock_response.context_usage = None
        mock_response.cited_uuids = []
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        original_steps = [{"step_number": 1, "description": "test", "verify_command": "echo ok", "expected_output": "ok"}]
        updated_steps = [
            {"step_number": 1, "description": "test", "verify_command": "echo ok", "expected_output": "ok", "status": "plan_defect"},
            {"step_number": 2, "description": "fix step", "verify_command": "echo OK", "expected_output": "OK"},
        ]
        mock_get_steps.return_value = updated_steps

        # First verify: fail, second verify (after re-read): pass
        mock_verify.side_effect = [
            [{"step_number": 1, "passed": False, "output": "error", "reason": "failed", "returncode": 1}],
            [{"step_number": 1, "passed": True, "output": "ok", "reason": "", "returncode": 0}],
        ]

        mock_smoke_result = MagicMock()
        mock_smoke_result.passed = True
        mock_smoke_result.files_tested = []
        mock_smoke.return_value = mock_smoke_result

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
            "steps_from_table": original_steps,
        }

        with patch("app.tasks.autonomous.execution.update_subtask_passes"), \
             patch("app.tasks.autonomous.execution.insert_subtask_summary"), \
             patch("app.storage.tasks.core.add_agent_hub_session"):
            result = _execute_subtask("task-1", subtask, "test-project", {})

        assert result["status"] == "passed"
        mock_get_steps.assert_called_once_with("sub-1")

    @patch("app.tasks.autonomous.execution._emit_log")
    @patch("app.tasks.autonomous.execution._emit_progress")
    @patch("app.tasks.autonomous.execution._emit_progress_log")
    @patch("app.tasks.autonomous.execution.run_smoke_tests")
    @patch("app.tasks.autonomous.execution.get_steps_for_subtask")
    @patch("app.tasks.autonomous.execution._verify_steps")
    @patch("app.tasks.autonomous.execution._check_worktree_health")
    @patch("app.tasks.autonomous.execution._get_project_path")
    @patch("app.tasks.autonomous.execution._build_subtask_prompt")
    @patch("app.tasks.autonomous.execution.get_sync_client")
    @patch("app.tasks.autonomous.execution._has_uncommitted_changes")
    @patch("app.tasks.autonomous.execution.get_handoff_context")
    @patch("app.tasks.autonomous.execution.get_task_spirit")
    @patch("app.tasks.autonomous.execution.acknowledge_no_citations", create=True)
    def test_steps_not_reread_on_first_attempt(
        self,
        mock_ack_citations: MagicMock,
        mock_spirit: MagicMock,
        mock_handoff: MagicMock,
        mock_uncommitted: MagicMock,
        mock_client_factory: MagicMock,
        mock_build_prompt: MagicMock,
        mock_project_path: MagicMock,
        mock_worktree_health: MagicMock,
        mock_verify: MagicMock,
        mock_get_steps: MagicMock,
        mock_smoke: MagicMock,
        mock_progress_log: MagicMock,
        mock_progress: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """get_steps_for_subtask is NOT called on first attempt (uses caller data)."""
        from app.tasks.autonomous.execution import _execute_subtask

        mock_project_path.return_value = "/tmp/test-worktree"
        mock_worktree_health.return_value = True
        mock_build_prompt.return_value = "test prompt"
        mock_uncommitted.return_value = False
        mock_spirit.return_value = {"objective": "test", "spirit_anti": ""}
        mock_handoff.return_value = {}

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "done"
        mock_response.session_id = "session-1"
        mock_response.progress_log = []
        mock_response.context_usage = None
        mock_response.cited_uuids = []
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        # All steps pass on first attempt
        mock_verify.return_value = [
            {"step_number": 1, "passed": True, "output": "ok", "reason": "", "returncode": 0},
        ]

        mock_smoke_result = MagicMock()
        mock_smoke_result.passed = True
        mock_smoke_result.files_tested = []
        mock_smoke.return_value = mock_smoke_result

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
            "steps_from_table": [{"step_number": 1, "description": "test", "verify_command": "echo ok"}],
        }

        with patch("app.tasks.autonomous.execution.update_subtask_passes"), \
             patch("app.tasks.autonomous.execution.insert_subtask_summary"), \
             patch("app.storage.tasks.core.add_agent_hub_session"):
            result = _execute_subtask("task-1", subtask, "test-project", {})

        assert result["status"] == "passed"
        mock_get_steps.assert_not_called()


class TestMergeBlockedWhenTaskRunning:
    """Bug #2, Layer A: Merge operations blocked when task is running."""

    @patch("app.tasks.autonomous.cleanup.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.get_task_worktree")
    @patch("app.tasks.autonomous.cleanup.task_store")
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

    @patch("app.tasks.autonomous.cleanup.subprocess")
    @patch("app.tasks.autonomous.cleanup.get_project_root_path")
    @patch("app.tasks.autonomous.cleanup.remove_task_worktree")
    @patch("app.tasks.autonomous.cleanup.get_task_worktree")
    @patch("app.tasks.autonomous.cleanup.task_store")
    def test_merge_allowed_when_task_completed(
        self,
        mock_store: MagicMock,
        mock_worktree: MagicMock,
        mock_remove: MagicMock,
        mock_root: MagicMock,
        mock_subprocess: MagicMock,
    ) -> None:
        """merge_and_cleanup_task_worktree proceeds when status != running."""
        from app.tasks.autonomous.cleanup import merge_and_cleanup_task_worktree

        mock_store.get_task.return_value = {"id": "task-1", "status": "completed"}

        worktree_obj = MagicMock()
        worktree_obj.branch = "task-1/main"
        worktree_obj.base_branch = "main"
        mock_worktree.return_value = worktree_obj

        mock_root.return_value = "/home/test/project"

        checkout_result = MagicMock()
        checkout_result.returncode = 0
        merge_result = MagicMock()
        merge_result.returncode = 0
        delete_result = MagicMock()
        delete_result.returncode = 0
        mock_subprocess.run.side_effect = [checkout_result, merge_result, delete_result]

        result = merge_and_cleanup_task_worktree("task-1", "test-project")

        assert result["status"] == "merged"


class TestWorktreeHealthCheck:
    """Bug #2, Layer B: Worktree health check function."""

    @patch("app.tasks.autonomous.execution._emit_log")
    def test_worktree_health_check_missing_dir(
        self,
        mock_log: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Returns False and logs error when directory doesn't exist."""
        from app.tasks.autonomous.execution import _check_worktree_health

        missing = str(tmp_path / "nonexistent")
        result = _check_worktree_health(missing, "task-1", "test-project")

        assert result is False
        mock_log.assert_called_once()
        assert "WORKTREE GONE" in mock_log.call_args[0][2]

    @patch("app.tasks.autonomous.execution._emit_log")
    def test_worktree_health_check_no_git_marker(
        self,
        mock_log: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Returns False when directory exists but has no .git marker."""
        from app.tasks.autonomous.execution import _check_worktree_health

        result = _check_worktree_health(str(tmp_path), "task-1", "test-project")

        assert result is False
        mock_log.assert_called_once()
        assert "WORKTREE CORRUPTED" in mock_log.call_args[0][2]

    @patch("app.tasks.autonomous.execution._emit_log")
    def test_worktree_health_check_valid(
        self,
        mock_log: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Returns True for a valid worktree directory with .git marker."""
        from app.tasks.autonomous.execution import _check_worktree_health

        (tmp_path / ".git").mkdir()
        result = _check_worktree_health(str(tmp_path), "task-1", "test-project")

        assert result is True
        mock_log.assert_not_called()

    @patch("app.tasks.autonomous.execution._emit_log")
    def test_worktree_health_check_valid_git_file(
        self,
        mock_log: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Returns True when .git is a file (worktree gitlink)."""
        from app.tasks.autonomous.execution import _check_worktree_health

        (tmp_path / ".git").write_text("gitdir: /path/to/main/.git/worktrees/task-1")
        result = _check_worktree_health(str(tmp_path), "task-1", "test-project")

        assert result is True
        mock_log.assert_not_called()


class TestHealLoopAbortsOnInvalidWorktree:
    """Bug #2, Layer B: Heal loop breaks immediately on worktree destruction."""

    @patch("app.tasks.autonomous.execution._emit_log")
    @patch("app.tasks.autonomous.execution._emit_progress")
    @patch("app.tasks.autonomous.execution._emit_progress_log")
    @patch("app.tasks.autonomous.execution._check_worktree_health")
    @patch("app.tasks.autonomous.execution._get_project_path")
    @patch("app.tasks.autonomous.execution._build_subtask_prompt")
    @patch("app.tasks.autonomous.execution.get_sync_client")
    @patch("app.tasks.autonomous.execution._has_uncommitted_changes")
    @patch("app.tasks.autonomous.execution.get_handoff_context")
    @patch("app.tasks.autonomous.execution.get_task_spirit")
    @patch("app.tasks.autonomous.execution.acknowledge_no_citations", create=True)
    def test_heal_loop_aborts_on_invalid_worktree(
        self,
        mock_ack_citations: MagicMock,
        mock_spirit: MagicMock,
        mock_handoff: MagicMock,
        mock_uncommitted: MagicMock,
        mock_client_factory: MagicMock,
        mock_build_prompt: MagicMock,
        mock_project_path: MagicMock,
        mock_worktree_health: MagicMock,
        mock_progress_log: MagicMock,
        mock_progress: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Subtask fails immediately when worktree is destroyed."""
        from app.tasks.autonomous.execution import _execute_subtask

        mock_project_path.return_value = "/tmp/test-worktree"
        # First call (initial guard) passes, second call (heal loop) fails
        mock_worktree_health.side_effect = [True, False]
        mock_build_prompt.return_value = "test prompt"
        mock_uncommitted.return_value = False
        mock_spirit.return_value = {"objective": "test", "spirit_anti": ""}
        mock_handoff.return_value = {}

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "done"
        mock_response.session_id = "session-1"
        mock_response.progress_log = []
        mock_response.context_usage = None
        mock_response.cited_uuids = []
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
            "steps_from_table": [{"step_number": 1, "description": "test"}],
        }

        with patch("app.storage.tasks.core.add_agent_hub_session"):
            result = _execute_subtask("task-1", subtask, "test-project", {})

        assert result["status"] == "failed"


class TestInitialWorktreeGuard:
    """Bug #2, Layer C: Initial worktree check before agent call."""

    @patch("app.tasks.autonomous.execution._emit_log")
    @patch("app.tasks.autonomous.execution._emit_progress")
    @patch("app.tasks.autonomous.execution._check_worktree_health")
    @patch("app.tasks.autonomous.execution._get_project_path")
    def test_execute_subtask_fails_on_invalid_worktree(
        self,
        mock_project_path: MagicMock,
        mock_worktree_health: MagicMock,
        mock_progress: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """_execute_subtask returns failed when worktree is invalid at start."""
        from app.tasks.autonomous.execution import _execute_subtask

        mock_project_path.return_value = "/tmp/nonexistent"
        mock_worktree_health.return_value = False

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
            "steps_from_table": [],
        }

        result = _execute_subtask("task-1", subtask, "test-project", {})

        assert result["status"] == "failed"
        assert result["reason"] == "worktree_invalid"


class TestMainRepoLeakageDetection:
    """Detect when agent writes files to main repo instead of worktree."""

    @patch("app.tasks.autonomous.execution._emit_log")
    @patch("app.tasks.autonomous.execution.subprocess")
    @patch("app.tasks.autonomous.execution.get_project_root_path")
    def test_leakage_detected_when_main_repo_dirty(
        self,
        mock_root: MagicMock,
        mock_subprocess: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Returns True and logs warning when main repo has uncommitted changes."""
        from app.tasks.autonomous.execution import _check_main_repo_leakage

        mock_root.return_value = "/home/test/project"
        result_obj = MagicMock()
        result_obj.stdout = " M leaked_file.py\n"
        mock_subprocess.run.return_value = result_obj

        detected = _check_main_repo_leakage("task-1", "test-project", "/tmp/worktree")

        assert detected is True
        assert any("WORKTREE LEAKAGE" in str(c) for c in mock_log.call_args_list)

    @patch("app.tasks.autonomous.execution._emit_log")
    @patch("app.tasks.autonomous.execution.subprocess")
    @patch("app.tasks.autonomous.execution.get_project_root_path")
    def test_no_leakage_when_main_repo_clean(
        self,
        mock_root: MagicMock,
        mock_subprocess: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Returns False when main repo is clean."""
        from app.tasks.autonomous.execution import _check_main_repo_leakage

        mock_root.return_value = "/home/test/project"
        result_obj = MagicMock()
        result_obj.stdout = ""
        mock_subprocess.run.return_value = result_obj

        detected = _check_main_repo_leakage("task-1", "test-project", "/tmp/worktree")

        assert detected is False

    @patch("app.tasks.autonomous.execution._emit_log")
    @patch("app.tasks.autonomous.execution.get_project_root_path")
    def test_skipped_when_same_path(
        self,
        mock_root: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Returns False immediately when project_path equals main root."""
        from app.tasks.autonomous.execution import _check_main_repo_leakage

        mock_root.return_value = "/home/test/project"

        detected = _check_main_repo_leakage("task-1", "test-project", "/home/test/project")

        assert detected is False
        mock_log.assert_not_called()


class TestZeroStepSubtask:
    """Zero-step subtask must fail verification, not silently pass."""

    @patch("app.tasks.autonomous.execution._emit_log")
    @patch("app.tasks.autonomous.execution._emit_progress")
    @patch("app.tasks.autonomous.execution._emit_progress_log")
    @patch("app.tasks.autonomous.execution._check_worktree_health")
    @patch("app.tasks.autonomous.execution._get_project_path")
    @patch("app.tasks.autonomous.execution._build_subtask_prompt")
    @patch("app.tasks.autonomous.execution.get_sync_client")
    @patch("app.tasks.autonomous.execution._has_uncommitted_changes")
    @patch("app.tasks.autonomous.execution.get_handoff_context")
    @patch("app.tasks.autonomous.execution.get_task_spirit")
    @patch("app.tasks.autonomous.execution.acknowledge_no_citations", create=True)
    def test_zero_steps_returns_failed(
        self,
        mock_ack_citations: MagicMock,
        mock_spirit: MagicMock,
        mock_handoff: MagicMock,
        mock_uncommitted: MagicMock,
        mock_client_factory: MagicMock,
        mock_build_prompt: MagicMock,
        mock_project_path: MagicMock,
        mock_worktree_health: MagicMock,
        mock_progress_log: MagicMock,
        mock_progress: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Subtask with 0 steps returns failed with reason=zero_steps."""
        from app.tasks.autonomous.execution import _execute_subtask

        mock_project_path.return_value = "/tmp/test-worktree"
        mock_worktree_health.return_value = True
        mock_build_prompt.return_value = "test prompt"
        mock_uncommitted.return_value = False
        mock_spirit.return_value = {"objective": "test", "spirit_anti": ""}
        mock_handoff.return_value = {}

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "done"
        mock_response.session_id = "session-1"
        mock_response.progress_log = []
        mock_response.context_usage = None
        mock_response.cited_uuids = []
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "empty subtask",
            "steps_from_table": [],
        }

        with patch("app.storage.tasks.core.add_agent_hub_session"):
            result = _execute_subtask("task-1", subtask, "test-project", {})

        assert result["status"] == "failed"
        assert result["reason"] == "zero_steps"
        assert result["passed"] is False
