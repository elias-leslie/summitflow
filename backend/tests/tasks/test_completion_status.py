"""Tests for task completion status transitions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.completion_status import (
    transition_to_complete,
)

MODULE = "app.tasks.autonomous.exec_modules.completion_status"


class TestTransitionToComplete:
    """Tests for transition_to_complete.

    The AI-Review tier and auto-merge arm have been removed; the function now
    always sets status=completed and runs checkpoint cleanup.
    """

    @patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.cleanup_task_checkpoint")
    @patch(f"{MODULE}.task_store")
    def test_completes_and_runs_cleanup(
        self, mock_store: MagicMock, mock_cleanup: MagicMock
    ) -> None:
        """Status flips to completed and checkpoint cleanup runs."""
        mock_cleanup.return_value = {"status": "cleaned", "checkout_path": "/tmp/wt"}

        result = transition_to_complete("t-1", "proj", "test")

        assert result == "completed"
        mock_store.update_task_status.assert_called_with("t-1", "completed")
        mock_cleanup.assert_called_once_with("t-1", delete_branch=False, project_id="proj")

    @patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.cleanup_task_checkpoint")
    @patch(f"{MODULE}.task_store")
    def test_dispatch_argument_is_ignored(
        self, mock_store: MagicMock, mock_cleanup: MagicMock
    ) -> None:
        """The legacy `dispatch` parameter is accepted but never invoked."""
        mock_cleanup.return_value = {"status": "cleaned", "checkout_path": "/tmp/wt"}
        dispatch = MagicMock()

        result = transition_to_complete("t-1", "proj", "test", dispatch)

        assert result == "completed"
        dispatch.assert_not_called()
