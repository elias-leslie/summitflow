"""Tests for autocode heal loop bug fixes.

Covers:
- Bug #1: Steps re-read from DB after heal attempts (st step defect picked up)
- Bug #2: Validation of execution environment before agent call.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Module path constants for patching
# ---------------------------------------------------------------------------
_SUBTASK_VALIDATION = "app.tasks.autonomous.exec_modules.subtask_validation"


class TestZeroStepSubtask:
    """Zero-step subtask logs a warning but does not fail — uses smoke tests only."""

    @patch(f"{_SUBTASK_VALIDATION}.emit_log")
    def test_zero_steps_returns_none(
        self,
        mock_log: MagicMock,
    ) -> None:
        """Subtask with 0 steps returns None (passes env check) and logs an info message."""
        from app.tasks.autonomous.exec_modules.subtask_validation import (
            validate_subtask_environment,
        )

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "empty subtask",
            "steps_from_table": [],
        }

        result = validate_subtask_environment(
            "task-1", subtask, "1.1", "/tmp/test-checkout", "test-project"
        )

        # Zero steps is now valid — execution proceeds with smoke tests only
        assert result is None


class TestWorkProductDetection:
    """Verification should treat dirty checkout edits as valid work product."""

    @patch("app.tasks.autonomous.exec_modules.quality_check.subprocess.run")
    def test_has_work_product_when_branch_has_commits(self, mock_run: MagicMock) -> None:
        """A branch commit beyond main counts as work product."""
        from app.tasks.autonomous.exec_modules.quality_check import _has_work_product

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),  # detect base branch
            MagicMock(returncode=0, stdout="abc123 change\n"),  # git log main..HEAD
        ]

        assert _has_work_product("/tmp/test-checkout")

    @patch("app.tasks.autonomous.exec_modules.quality_check.subprocess.run")
    def test_has_work_product_when_checkout_has_uncommitted_changes(
        self,
        mock_run: MagicMock,
    ) -> None:
        """Dirty checkout edits should count even before a commit exists."""
        from app.tasks.autonomous.exec_modules.quality_check import _has_work_product

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),  # detect base branch
            MagicMock(returncode=0, stdout=""),  # git log (no commits)
            MagicMock(stdout=" M a_term/api/handlers/websocket_resize.py\n"),  # git status
        ]

        assert _has_work_product("/tmp/test-checkout")

    @patch("app.tasks.autonomous.exec_modules.quality_check.subprocess.run")
    def test_has_work_product_detects_master_branch(self, mock_run: MagicMock) -> None:
        """Repos using 'master' as default branch should be detected."""
        from app.tasks.autonomous.exec_modules.quality_check import _has_work_product

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/master\n"),  # detect master
            MagicMock(returncode=0, stdout="abc123 fix\n"),  # git log master..HEAD
        ]

        assert _has_work_product("/tmp/test-checkout")
        # Verify git log used "master" not "main"
        log_call = mock_run.call_args_list[1]
        assert "master..HEAD" in log_call[0][0]

    @patch("app.tasks.autonomous.exec_modules.git_work_product.emit_log")
    @patch("app.tasks.autonomous.exec_modules.git_work_product.has_unpublished_commits")
    @patch("app.tasks.autonomous.exec_modules.git_work_product.smart_commit_result")
    @patch("app.tasks.autonomous.exec_modules.git_work_product.has_uncommitted_changes")
    def test_ensure_committed_work_product_commits_dirty_changes(
        self,
        mock_has_uncommitted_changes: MagicMock,
        mock_smart_commit_result: MagicMock,
        mock_has_unpublished_commits: MagicMock,
        mock_emit_log: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.git_work_product import ensure_committed_work_product

        mock_has_unpublished_commits.side_effect = [False, False]
        mock_has_uncommitted_changes.return_value = True
        mock_smart_commit_result.return_value = {"success": True}

        result = ensure_committed_work_product("task-1", "1.1", "/tmp/test-checkout", "agent-hub")

        assert result is None
        mock_emit_log.assert_called_once()
        mock_smart_commit_result.assert_called_once_with(
            "/tmp/test-checkout",
            "autocode(task-1): complete subtask 1.1",
            task_id="task-1",
            push=True,
        )

    @patch("app.tasks.autonomous.exec_modules.git_work_product.smart_commit_result")
    @patch("app.tasks.autonomous.exec_modules.git_work_product.has_uncommitted_changes")
    @patch("app.tasks.autonomous.exec_modules.git_work_product.has_unpublished_commits")
    def test_ensure_committed_work_product_surfaces_commit_failure_detail(
        self,
        mock_has_unpublished_commits: MagicMock,
        mock_has_uncommitted_changes: MagicMock,
        mock_smart_commit_result: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.git_work_product import ensure_committed_work_product

        mock_has_unpublished_commits.return_value = False
        mock_has_uncommitted_changes.return_value = True
        mock_smart_commit_result.return_value = {
            "success": False,
            "detail": (
                "commit helper failed: st commit "
                "--message 'autocode(task-1): complete subtask 1.1' --task task-1 --push; "
                "stderr: changed_only_types failed for backend/app/foo.py"
            ),
        }

        result = ensure_committed_work_product("task-1", "1.1", "/tmp/test-checkout", "agent-hub")

        assert result is not None
        assert "st commit" in result
        assert "--task task-1" in result
        assert "changed_only_types failed for backend/app/foo.py" in result

    @patch("app.tasks.autonomous.exec_modules.git_work_product.publish_existing_commits")
    @patch("app.tasks.autonomous.exec_modules.git_work_product.has_unpublished_commits")
    def test_ensure_committed_work_product_publishes_existing_commits(
        self,
        mock_has_unpublished_commits: MagicMock,
        mock_publish_existing_commits: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.git_work_product import ensure_committed_work_product

        mock_has_unpublished_commits.return_value = True
        mock_publish_existing_commits.return_value = True

        result = ensure_committed_work_product("task-1", "1.1", "/tmp/test-checkout", "agent-hub")

        assert result is None
        mock_publish_existing_commits.assert_called_once_with("/tmp/test-checkout")

    @patch("app.tasks.autonomous.exec_modules.git_work_product.has_uncommitted_changes")
    @patch("app.tasks.autonomous.exec_modules.git_work_product.has_unpublished_commits")
    def test_ensure_committed_work_product_fails_when_nothing_to_publish(
        self,
        mock_has_unpublished_commits: MagicMock,
        mock_has_uncommitted_changes: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.git_work_product import ensure_committed_work_product

        mock_has_unpublished_commits.return_value = False
        mock_has_uncommitted_changes.return_value = False

        result = ensure_committed_work_product("task-1", "1.1", "/tmp/test-checkout", "agent-hub")

        assert result == "No committed or dirty work product remains to publish"

    @patch("app.tasks.autonomous.exec_modules.quality_check.subprocess.run")
    def test_has_no_work_product_when_branch_clean_and_no_commits(
        self,
        mock_run: MagicMock,
    ) -> None:
        """No branch commits and no dirty files means nothing was produced."""
        from app.tasks.autonomous.exec_modules.quality_check import _has_work_product

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),  # detect base branch
            MagicMock(returncode=0, stdout=""),  # git log (no commits)
            MagicMock(stdout=""),  # git status (clean)
        ]

        assert not _has_work_product("/tmp/test-checkout")

    @patch("app.tasks.autonomous.exec_modules.quality_check.get_task_spirit")
    @patch("app.tasks.autonomous.exec_modules.quality_check.get_task")
    @patch("app.tasks.autonomous.exec_modules.quality_check.subprocess.run")
    def test_run_execution_quality_check_allows_no_code_validation_tasks(
        self,
        mock_run: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        """Explicit workflow-only validation tasks should not fail on missing commits."""
        from app.tasks.autonomous.exec_modules.quality_check import run_execution_quality_check

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

        all_passed, _results = run_execution_quality_check(
            "task-1",
            "sub-1",
            [],
            "/tmp/test-checkout",
            "summitflow",
        )

        assert all_passed

    @patch("app.tasks.autonomous.exec_modules.quality_check.get_task_spirit")
    @patch("app.tasks.autonomous.exec_modules.quality_check.get_task")
    @patch("app.tasks.autonomous.exec_modules.quality_check.subprocess.run")
    def test_run_execution_quality_check_allows_inspect_only_steps_without_work_product(
        self,
        mock_run: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        """Inspect-only subtasks should not loop on missing commits."""
        from app.tasks.autonomous.exec_modules.quality_check import run_execution_quality_check

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
            MagicMock(returncode=0, stdout=""),
            MagicMock(stdout=""),
        ]
        mock_get_task.return_value = {
            "id": "task-1",
            "title": "Investigate migration behavior",
            "description": "Confirm the current behavior before deciding on a fix.",
        }
        mock_get_spirit.return_value = {}

        all_passed, _results = run_execution_quality_check(
            "task-1",
            "sub-1",
            [{"step_number": 1, "description": "Inspect the migration and confirm whether DELETE runs"}],
            "/tmp/test-checkout",
            "summitflow",
        )

        assert all_passed

    @patch("app.tasks.autonomous.exec_modules.quality_check.get_task_spirit")
    @patch("app.tasks.autonomous.exec_modules.quality_check.get_task")
    @patch("app.tasks.autonomous.exec_modules.quality_check.subprocess.run")
    def test_run_execution_quality_check_allows_feedback_resolution_without_work_product(
        self,
        mock_run: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        """Feedback cleanup can resolve external state without producing commits."""
        from app.tasks.autonomous.exec_modules.quality_check import run_execution_quality_check

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
            MagicMock(returncode=0, stdout=""),
            MagicMock(stdout=""),
        ]
        mock_get_task.return_value = {
            "id": "task-feedback",
            "title": "Handle feedback: compact manifest saves prompt tokens",
            "description": "Feedback ID: feedback-123",
        }
        mock_get_spirit.return_value = {
            "done_when": [
                "The underlying upkeep signal is resolved or explicitly marked obsolete with evidence"
            ],
        }

        all_passed, _results = run_execution_quality_check(
            "task-feedback",
            "sub-1",
            [{"step_number": 1, "description": "Resolve feedback item feedback-123"}],
            "/tmp/test-checkout",
            "summitflow",
        )

        assert all_passed

    @patch("app.tasks.autonomous.exec_modules.quality_check.get_task_spirit")
    @patch("app.tasks.autonomous.exec_modules.quality_check.get_task")
    @patch("app.tasks.autonomous.exec_modules.quality_check.subprocess.run")
    def test_run_execution_quality_check_still_requires_work_product_for_change_steps(
        self,
        mock_run: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        """Implementation steps must still produce a diff or commit."""
        from app.tasks.autonomous.exec_modules.quality_check import run_execution_quality_check

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
            MagicMock(returncode=0, stdout=""),
            MagicMock(stdout=""),
        ]
        mock_get_task.return_value = {
            "id": "task-1",
            "title": "Fix migration behavior",
            "description": "Implement the smallest safe correction.",
        }
        mock_get_spirit.return_value = {}

        all_passed, results = run_execution_quality_check(
            "task-1",
            "sub-1",
            [{"step_number": 1, "description": "Implement the migration fix and update the downgrade"}],
            "/tmp/test-checkout",
            "summitflow",
        )

        assert not all_passed
        assert results[0]["reason"] == "no_work_product"
