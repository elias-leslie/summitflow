"""Tests for AI review gate in st done flow."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import typer

from cli.commands.done_task import _run_ai_review


class TestRunAiReview:
    """Tests for _run_ai_review helper."""

    def test_returns_review_result_on_success(self) -> None:
        client = MagicMock()
        client._global_url.return_value = "http://test/tasks/task-1/review"
        client.post.return_value = {
            "verdict": "APPROVED",
            "concerns": [],
            "summary": "LGTM",
        }

        result = _run_ai_review(client, "task-1")

        assert result is not None
        assert result["verdict"] == "APPROVED"
        client.post.assert_called_once()

    def test_returns_none_on_api_error(self) -> None:
        client = MagicMock()
        client._global_url.return_value = "http://test/tasks/task-1/review"
        client.post.side_effect = Exception("Connection refused")

        result = _run_ai_review(client, "task-1")

        assert result is None

    def test_returns_none_on_timeout(self) -> None:
        client = MagicMock()
        client._global_url.return_value = "http://test/tasks/task-1/review"
        client.post.side_effect = TimeoutError("Request timed out")

        result = _run_ai_review(client, "task-1")

        assert result is None


class TestPerformCompletionReviewGate:
    """Tests for review gate integration in _perform_completion."""

    def _make_client(self) -> MagicMock:
        client = MagicMock()
        client._global_url = MagicMock(side_effect=lambda p: f"http://test{p}")
        client.get.return_value = {"ready": True, "gates": []}
        client.update_status.return_value = {"status": "completed"}
        return client

    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.report_task_outcome")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task._run_ai_review")
    @patch("cli.commands.done_task.auto_close_subtasks")
    def test_approved_review_proceeds(
        self,
        mock_auto: MagicMock,
        mock_review: MagicMock,
        mock_merge: MagicMock,
        mock_outcome: MagicMock,
        mock_remove: MagicMock,
    ) -> None:
        mock_review.return_value = {"verdict": "APPROVED", "concerns": []}
        client = self._make_client()
        snapshot: dict[str, Any] = {"project_id": "test", "created_at": None}

        from cli.commands.done_task import _perform_completion

        _perform_completion(client, "task-1", snapshot, "test", strict=False)

        mock_merge.assert_called_once()

    @patch("cli.commands.done_task._run_ai_review")
    @patch("cli.commands.done_task.auto_close_subtasks")
    def test_rejected_review_blocks_completion(
        self, mock_auto: MagicMock, mock_review: MagicMock
    ) -> None:
        mock_review.return_value = {
            "verdict": "NEEDS_FIX",
            "concerns": ["Missing error handling", "No tests"],
        }
        client = self._make_client()
        snapshot: dict[str, Any] = {"project_id": "test", "created_at": None}

        from cli.commands.done_task import _perform_completion

        with pytest.raises(typer.Exit):
            _perform_completion(client, "task-1", snapshot, "test", strict=False)

        # Should NOT have merged
        client.update_status.assert_not_called()

    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.report_task_outcome")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task._run_ai_review")
    @patch("cli.commands.done_task.auto_close_subtasks")
    def test_review_failure_non_blocking(
        self,
        mock_auto: MagicMock,
        mock_review: MagicMock,
        mock_merge: MagicMock,
        mock_outcome: MagicMock,
        mock_remove: MagicMock,
    ) -> None:
        """If review API fails (returns None), completion proceeds."""
        mock_review.return_value = None
        client = self._make_client()
        snapshot: dict[str, Any] = {"project_id": "test", "created_at": None}

        from cli.commands.done_task import _perform_completion

        _perform_completion(client, "task-1", snapshot, "test", strict=False)

        mock_merge.assert_called_once()

    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.report_task_outcome")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task._run_ai_review")
    @patch("cli.commands.done_task.auto_close_subtasks")
    def test_unknown_verdict_proceeds(
        self,
        mock_auto: MagicMock,
        mock_review: MagicMock,
        mock_merge: MagicMock,
        mock_outcome: MagicMock,
        mock_remove: MagicMock,
    ) -> None:
        """UNKNOWN verdict (e.g. parse failure) should not block."""
        mock_review.return_value = {"verdict": "UNKNOWN", "concerns": []}
        client = self._make_client()
        snapshot: dict[str, Any] = {"project_id": "test", "created_at": None}

        from cli.commands.done_task import _perform_completion

        _perform_completion(client, "task-1", snapshot, "test", strict=False)

        mock_merge.assert_called_once()

    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.report_task_outcome")
    @patch("cli.commands.done_task.task_store")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task._run_ai_review", return_value={"verdict": "APPROVED", "concerns": []})
    @patch("cli.commands.done_task.auto_close_subtasks")
    def test_status_update_falls_back_to_direct_storage_after_merge(
        self,
        mock_auto: MagicMock,
        mock_review: MagicMock,
        mock_merge: MagicMock,
        mock_task_store: MagicMock,
        mock_outcome: MagicMock,
        mock_remove: MagicMock,
    ) -> None:
        """Merged tasks should still be completed if the API status call fails."""
        client = self._make_client()
        client.update_status.side_effect = Exception("api unavailable")
        mock_task_store.update_task_status.return_value = {"status": "completed"}
        snapshot: dict[str, Any] = {"project_id": "test", "created_at": None}

        from cli.commands.done_task import _perform_completion

        _perform_completion(client, "task-1", snapshot, "test", strict=False)

        mock_merge.assert_called_once()
        mock_task_store.update_task_status.assert_called_once_with(
            "task-1",
            "completed",
            validate_transition=False,
        )

    @patch("cli.commands.done_task.task_store")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task._run_ai_review", return_value={"verdict": "APPROVED", "concerns": []})
    @patch("cli.commands.done_task.auto_close_subtasks")
    def test_status_update_failure_after_merge_raises_if_fallback_fails(
        self,
        mock_auto: MagicMock,
        mock_review: MagicMock,
        mock_merge: MagicMock,
        mock_task_store: MagicMock,
    ) -> None:
        """If both API and direct storage completion fail after merge, exit loudly."""
        client = self._make_client()
        client.update_status.side_effect = Exception("api unavailable")
        mock_task_store.update_task_status.side_effect = RuntimeError("db unavailable")
        snapshot: dict[str, Any] = {"project_id": "test", "created_at": None}

        from cli.commands.done_task import _perform_completion

        with pytest.raises(typer.Exit):
            _perform_completion(client, "task-1", snapshot, "test", strict=False)
