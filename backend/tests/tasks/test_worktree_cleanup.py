"""Tests for autonomous worktree cleanup safety."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.cleanup.worktree_cleanup import cleanup_task_worktree


@patch("app.tasks.autonomous.cleanup.worktree_cleanup.remove_task_worktree")
@patch("app.tasks.autonomous.cleanup.worktree_cleanup.has_uncommitted_changes")
@patch("app.tasks.autonomous.cleanup.worktree_cleanup.get_task_worktree")
def test_cleanup_task_worktree_skips_dirty_worktree(
    mock_get_worktree: MagicMock,
    mock_dirty: MagicMock,
    mock_remove: MagicMock,
) -> None:
    mock_worktree = MagicMock()
    mock_worktree.path = "/tmp/task-1"
    mock_worktree.branch = "task-1/main"
    mock_get_worktree.return_value = mock_worktree
    mock_dirty.return_value = True

    result = cleanup_task_worktree("task-1", project_id="proj")

    assert result == {"task_id": "task-1", "status": "skipped", "reason": "dirty_worktree"}
    mock_remove.assert_not_called()


@patch("app.tasks.autonomous.cleanup.worktree_cleanup.remove_task_worktree")
@patch("app.tasks.autonomous.cleanup.worktree_cleanup.has_uncommitted_changes")
@patch("app.tasks.autonomous.cleanup.worktree_cleanup.get_task_worktree")
def test_cleanup_task_worktree_removes_clean_worktree(
    mock_get_worktree: MagicMock,
    mock_dirty: MagicMock,
    mock_remove: MagicMock,
) -> None:
    mock_worktree = MagicMock()
    mock_worktree.path = "/tmp/task-1"
    mock_worktree.branch = "task-1/main"
    mock_get_worktree.return_value = mock_worktree
    mock_dirty.return_value = False
    mock_remove.return_value = True

    result = cleanup_task_worktree("task-1", project_id="proj")

    assert result == {
        "task_id": "task-1",
        "status": "cleaned",
        "worktree_path": "/tmp/task-1",
        "branch": "task-1/main",
        "branch_deleted": False,
    }
    mock_remove.assert_called_once_with(
        "task-1",
        delete_branch=False,
        project_id="proj",
    )
