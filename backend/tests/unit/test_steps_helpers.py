"""Tests for steps_helpers — verification cwd resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from app.api.tasks.steps_helpers import get_verification_cwd

WORKTREE_INFO_PATH = "cli.lib.worktree.get_worktree_info"
PROJECT_ROOT_PATH = "app.storage.projects.get_project_root_path"


class TestGetVerificationCwd:
    """Test that get_verification_cwd resolves worktree paths correctly."""

    @patch(PROJECT_ROOT_PATH)
    @patch(WORKTREE_INFO_PATH)
    def test_returns_worktree_path_when_exists(
        self, mock_get_worktree_info: Any, mock_get_root: Any
    ) -> None:
        """Worktree exists and is valid — should return worktree path."""
        worktree_path = Path("/home/user/.local/share/st/worktrees/summitflow/task-abc")
        mock_info = MagicMock()
        mock_info.path = MagicMock(spec=Path)
        mock_info.path.exists.return_value = True
        mock_info.path.__str__ = lambda self: str(worktree_path)
        mock_get_worktree_info.return_value = mock_info

        result = get_verification_cwd("summitflow", "task-abc")

        assert result == str(worktree_path)
        mock_get_worktree_info.assert_called_once_with("task-abc", "summitflow")
        mock_get_root.assert_not_called()

    @patch(PROJECT_ROOT_PATH)
    @patch(WORKTREE_INFO_PATH)
    def test_falls_back_to_project_root_when_no_worktree(
        self, mock_get_worktree_info: Any, mock_get_root: Any
    ) -> None:
        """No worktree — should fall back to project root."""
        mock_get_worktree_info.return_value = None
        mock_get_root.return_value = "/home/user/summitflow"

        result = get_verification_cwd("summitflow", "task-abc")

        assert result == "/home/user/summitflow"
        mock_get_worktree_info.assert_called_once_with("task-abc", "summitflow")
        mock_get_root.assert_called_once_with("summitflow")

    @patch(PROJECT_ROOT_PATH)
    @patch(WORKTREE_INFO_PATH)
    def test_passes_project_id_to_worktree_lookup(
        self, mock_get_worktree_info: Any, mock_get_root: Any
    ) -> None:
        """Critical: project_id must be passed to get_worktree_info."""
        mock_get_worktree_info.return_value = None
        mock_get_root.return_value = "/home/user/agent-hub"

        get_verification_cwd("agent-hub", "task-xyz")

        # Verify project_id is passed (the bug was missing this)
        mock_get_worktree_info.assert_called_once_with("task-xyz", "agent-hub")

    @patch(PROJECT_ROOT_PATH)
    @patch(WORKTREE_INFO_PATH)
    def test_falls_back_when_worktree_path_missing(
        self, mock_get_worktree_info: Any, mock_get_root: Any
    ) -> None:
        """Worktree info exists but path doesn't — should fall back."""
        mock_info = MagicMock()
        mock_info.path.exists.return_value = False
        mock_get_worktree_info.return_value = mock_info
        mock_get_root.return_value = "/home/user/summitflow"

        result = get_verification_cwd("summitflow", "task-abc")

        assert result == "/home/user/summitflow"

    @patch(PROJECT_ROOT_PATH)
    @patch(WORKTREE_INFO_PATH)
    def test_no_task_id_skips_worktree_lookup(
        self, mock_get_worktree_info: Any, mock_get_root: Any
    ) -> None:
        """Empty task_id should skip worktree check entirely."""
        mock_get_root.return_value = "/home/user/summitflow"

        result = get_verification_cwd("summitflow", "")

        assert result == "/home/user/summitflow"
        mock_get_worktree_info.assert_not_called()
