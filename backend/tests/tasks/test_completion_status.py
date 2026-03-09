"""Tests for task completion status transitions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.completion_status import (
    transition_to_review_or_complete,
)

MODULE = "app.tasks.autonomous.exec_modules.completion_status"


class TestTransitionToReviewOrComplete:
    """Tests for transition_to_review_or_complete."""

    @patch(f"{MODULE}.agent_configs")
    @patch(f"{MODULE}.task_store")
    def test_review_enabled_dispatches_review(
        self, mock_store: MagicMock, mock_configs: MagicMock
    ) -> None:
        """When project requires review and task has ai_review=True, dispatch review."""
        mock_configs.get_require_review.return_value = True
        mock_store.get_task.return_value = {"id": "t-1", "ai_review": True}
        dispatch = MagicMock()

        result = transition_to_review_or_complete("t-1", "proj", "test", dispatch)

        assert result == "ai_reviewing"
        mock_store.update_task_status.assert_called_with("t-1", "ai_reviewing")
        dispatch.assert_called_once_with("review", "t-1", "proj")

    @patch("app.tasks.autonomous.cleanup.worktree_cleanup.cleanup_task_worktree")
    @patch(f"{MODULE}.agent_configs")
    @patch(f"{MODULE}.task_store")
    def test_review_disabled_completes(
        self, mock_store: MagicMock, mock_configs: MagicMock, mock_cleanup: MagicMock
    ) -> None:
        """When project does not require review, complete immediately."""
        mock_configs.get_require_review.return_value = False
        mock_configs.get_auto_merge_enabled.return_value = False
        mock_cleanup.return_value = {"status": "cleaned", "worktree_path": "/tmp/wt"}

        result = transition_to_review_or_complete("t-1", "proj", "test")

        assert result == "completed"
        mock_store.update_task_status.assert_called_with("t-1", "completed")
        mock_cleanup.assert_called_once_with("t-1", delete_branch=False, project_id="proj")

    @patch("app.tasks.autonomous.cleanup.worktree_cleanup.cleanup_task_worktree")
    @patch(f"{MODULE}.agent_configs")
    @patch(f"{MODULE}.task_store")
    def test_task_ai_review_false_skips_review(
        self, mock_store: MagicMock, mock_configs: MagicMock, mock_cleanup: MagicMock
    ) -> None:
        """Task-level ai_review=False overrides project-level require_review=True."""
        mock_configs.get_require_review.return_value = True
        mock_configs.get_auto_merge_enabled.return_value = False
        mock_store.get_task.return_value = {"id": "t-1", "ai_review": False}
        mock_cleanup.return_value = {"status": "cleaned", "worktree_path": "/tmp/wt"}
        dispatch = MagicMock()

        result = transition_to_review_or_complete("t-1", "proj", "test", dispatch)

        assert result == "completed"
        mock_store.update_task_status.assert_called_with("t-1", "completed")
        dispatch.assert_not_called()
        mock_cleanup.assert_called_once_with("t-1", delete_branch=False, project_id="proj")

    @patch("app.tasks.autonomous.cleanup.merge_operations.merge_and_cleanup_task_worktree")
    @patch(f"{MODULE}.agent_configs")
    @patch(f"{MODULE}.task_store")
    def test_review_disabled_dispatches_merge_cleanup_when_auto_merge_enabled(
        self, mock_store: MagicMock, mock_configs: MagicMock, mock_merge_cleanup: MagicMock
    ) -> None:
        mock_configs.get_require_review.return_value = False
        mock_configs.get_auto_merge_enabled.return_value = True
        mock_merge_cleanup.return_value = {"status": "merged"}
        dispatch = MagicMock()

        result = transition_to_review_or_complete("t-1", "proj", "test", dispatch)

        assert result == "completed"
        dispatch.assert_not_called()
        mock_store.update_task_status.assert_not_called()
        mock_merge_cleanup.assert_called_once_with("t-1", "proj")

    @patch("app.tasks.autonomous.cleanup.merge_operations.merge_and_cleanup_task_worktree")
    @patch(f"{MODULE}.agent_configs")
    @patch(f"{MODULE}.task_store")
    def test_review_disabled_auto_merge_conflict_returns_conflicted(
        self, mock_store: MagicMock, mock_configs: MagicMock, mock_merge_cleanup: MagicMock
    ) -> None:
        mock_configs.get_require_review.return_value = False
        mock_configs.get_auto_merge_enabled.return_value = True
        mock_merge_cleanup.return_value = {"status": "conflicted"}

        result = transition_to_review_or_complete("t-1", "proj", "test")

        assert result == "conflicted"

    @patch(f"{MODULE}.agent_configs")
    @patch(f"{MODULE}.task_store")
    def test_task_ai_review_none_defaults_to_review(
        self, mock_store: MagicMock, mock_configs: MagicMock
    ) -> None:
        """When task has no ai_review field, default to project setting."""
        mock_configs.get_require_review.return_value = True
        mock_store.get_task.return_value = {"id": "t-1"}
        dispatch = MagicMock()

        result = transition_to_review_or_complete("t-1", "proj", "test", dispatch)

        assert result == "ai_reviewing"
        dispatch.assert_called_once()

    @patch(f"{MODULE}.agent_configs")
    @patch(f"{MODULE}.task_store")
    def test_task_not_found_defaults_to_review(
        self, mock_store: MagicMock, mock_configs: MagicMock
    ) -> None:
        """When task fetch returns None, default to project setting."""
        mock_configs.get_require_review.return_value = True
        mock_store.get_task.return_value = None
        dispatch = MagicMock()

        result = transition_to_review_or_complete("t-1", "proj", "test", dispatch)

        assert result == "ai_reviewing"
        dispatch.assert_called_once()
