"""Tests for verification guards: null verify_command rejection + zero-diff review guard.

Covers:
- verify_step() returns passed=False when verify_command is null/empty
- _verify_steps() propagates the failure correctly
- AI review rejects tasks with zero diff
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.tasks.autonomous.verification import verify_step


class TestNullVerifyCommandGuard:
    """verify_step() must fail when verify_command is missing."""

    def test_null_verify_command_returns_failed(self) -> None:
        step = {"step_number": 1, "verify_command": None}
        result = verify_step(step, "/tmp/fake-worktree")

        assert not result.passed
        assert result.reason == "missing_verify_command"
        assert result.returncode == -1
        assert "no verify_command" in result.output

    def test_empty_string_verify_command_returns_failed(self) -> None:
        step = {"step_number": 2, "verify_command": ""}
        result = verify_step(step, "/tmp/fake-worktree")

        assert not result.passed
        assert result.reason == "missing_verify_command"

    def test_valid_verify_command_still_runs(self) -> None:
        step = {"step_number": 1, "verify_command": "echo ok"}
        result = verify_step(step, "/tmp")

        assert result.passed
        assert result.returncode == 0

    def test_verify_steps_propagates_null_failure(self) -> None:
        """_verify_steps should mark step as failed and short-circuit remaining."""
        from app.tasks.autonomous.execution import _verify_steps

        steps: list[dict[str, Any]] = [
            {"step_number": 1, "verify_command": None},
            {"step_number": 2, "verify_command": "echo ok"},
        ]

        with (
            patch("app.tasks.autonomous.exec_modules.step_verification.update_step_passes"),
            patch("app.tasks.autonomous.exec_modules.step_verification.emit_log"),
            patch("app.tasks.autonomous.exec_modules.step_verification.emit_progress"),
        ):
            results = _verify_steps("task-test", "1.1", steps, "/tmp", "test-project")

        assert len(results) == 2
        assert not results[0]["passed"]
        assert results[0]["reason"] == "missing_verify_command"
        assert not results[1]["passed"]
        assert "skipped" in results[1]["output"].lower()


class TestZeroDiffReviewGuard:
    """AI review must reject tasks with zero diff."""

    @patch("app.tasks.autonomous.review.create_task_failure_notification")
    @patch("app.tasks.autonomous.review.task_store")
    @patch("app.tasks.autonomous.review.log_task_event")
    @patch("app.tasks.autonomous.review.get_git_diff", return_value="(no changes)")
    def test_zero_diff_rejects_review(
        self,
        mock_diff: MagicMock,
        mock_log: MagicMock,
        mock_store: MagicMock,
        mock_notification: MagicMock,
    ) -> None:
        from app.tasks.autonomous.review import ai_review

        mock_store.get_task.return_value = {"title": "Test task", "complexity": "SIMPLE"}

        result = ai_review("task-zero", "test-project")

        assert result["status"] == "rejected"
        assert result["verdict"] == "REJECTED"
        assert "no code changes" in result["message"].lower()
        mock_store.update_task_status.assert_called_with("task-zero", "failed")

    @patch("app.tasks.autonomous.review.create_task_failure_notification")
    @patch("app.tasks.autonomous.review.task_store")
    @patch("app.tasks.autonomous.review.log_task_event")
    @patch("app.tasks.autonomous.review.get_git_diff", return_value="")
    def test_empty_diff_rejects_review(
        self,
        mock_diff: MagicMock,
        mock_log: MagicMock,
        mock_store: MagicMock,
        mock_notification: MagicMock,
    ) -> None:
        from app.tasks.autonomous.review import ai_review

        mock_store.get_task.return_value = {"title": "Test task"}

        result = ai_review("task-empty", "test-project")

        assert result["status"] == "rejected"

    @patch("app.tasks.autonomous.review.task_store")
    @patch("app.tasks.autonomous.review.log_task_event")
    @patch("app.tasks.autonomous.review.get_git_diff", return_value="diff --git a/foo.py b/foo.py\n+new line")
    @patch("app.tasks.autonomous.review.get_task_spirit", return_value=None)
    @patch("app.tasks.autonomous.review.get_sync_client")
    def test_real_diff_proceeds_to_review(
        self,
        mock_client: MagicMock,
        mock_spirit: MagicMock,
        mock_diff: MagicMock,
        mock_log: MagicMock,
        mock_store: MagicMock,
    ) -> None:
        from app.tasks.autonomous.review import ai_review

        mock_store.get_task.return_value = {"title": "Real task", "complexity": "SIMPLE"}

        mock_response = MagicMock()
        mock_response.content = '{"verdict": "APPROVED", "summary": "LGTM"}'
        mock_client.return_value.complete.return_value = mock_response

        with patch("app.tasks.autonomous.review.route_based_on_verdict"):
            result = ai_review("task-real", "test-project")

        assert result["status"] == "reviewed"
        assert result["verdict"] == "APPROVED"
