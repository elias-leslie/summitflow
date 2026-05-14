"""Tests for task completion status transitions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.completion_status import (
    transition_to_complete,
)

MODULE = "app.tasks.autonomous.exec_modules.completion_status"


class TestTransitionToComplete:
    """Tests for transition_to_complete.

    The AI-Review tier has been removed; this function now always routes through
    the deterministic complete-and-merge path regardless of project config.
    """

    @patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.cleanup_task_checkpoint")
    @patch(f"{MODULE}.agent_configs")
    @patch(f"{MODULE}.task_store")
    def test_completes_when_auto_merge_disabled(
        self, mock_store: MagicMock, mock_configs: MagicMock, mock_cleanup: MagicMock
    ) -> None:
        """Without auto-merge, status flips to completed and checkpoint cleanup runs."""
        mock_configs.get_auto_merge_enabled.return_value = False
        mock_cleanup.return_value = {"status": "cleaned", "checkout_path": "/tmp/wt"}

        result = transition_to_complete("t-1", "proj", "test")

        assert result == "completed"
        mock_store.update_task_status.assert_called_with("t-1", "completed")
        mock_cleanup.assert_called_once_with("t-1", delete_branch=False, project_id="proj")

    @patch("app.tasks.autonomous.cleanup.merge_operations.merge_and_cleanup_task_checkpoint")
    @patch(f"{MODULE}.agent_configs")
    @patch(f"{MODULE}.task_store")
    def test_dispatches_merge_cleanup_when_auto_merge_enabled(
        self, mock_store: MagicMock, mock_configs: MagicMock, mock_merge_cleanup: MagicMock
    ) -> None:
        mock_configs.get_auto_merge_enabled.return_value = True
        mock_merge_cleanup.return_value = {"status": "merged"}

        result = transition_to_complete("t-1", "proj", "test")

        assert result == "completed"
        mock_store.update_task_status.assert_called_once_with(
            "t-1", "completed", validate_transition=False,
        )
        mock_merge_cleanup.assert_called_once_with("t-1", "proj")

    @patch("app.tasks.autonomous.cleanup.merge_operations.merge_and_cleanup_task_checkpoint")
    @patch(f"{MODULE}.agent_configs")
    @patch(f"{MODULE}.task_store")
    def test_auto_merge_conflict_returns_failed(
        self, mock_store: MagicMock, mock_configs: MagicMock, mock_merge_cleanup: MagicMock
    ) -> None:
        mock_configs.get_auto_merge_enabled.return_value = True
        mock_merge_cleanup.return_value = {"status": "conflicted"}

        result = transition_to_complete("t-1", "proj", "test")

        assert result == "failed"

    @patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.cleanup_task_checkpoint")
    @patch(f"{MODULE}.agent_configs")
    @patch(f"{MODULE}.task_store")
    def test_dispatch_argument_is_ignored(
        self, mock_store: MagicMock, mock_configs: MagicMock, mock_cleanup: MagicMock
    ) -> None:
        """The legacy `dispatch` parameter is accepted but never invoked."""
        mock_configs.get_auto_merge_enabled.return_value = False
        mock_cleanup.return_value = {"status": "cleaned", "checkout_path": "/tmp/wt"}
        dispatch = MagicMock()

        result = transition_to_complete("t-1", "proj", "test", dispatch)

        assert result == "completed"
        dispatch.assert_not_called()
