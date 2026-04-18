"""Tests for autonomous checkpoint cleanup safety."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.cleanup.checkpoint_cleanup import cleanup_task_checkpoint


@patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.remove_task_checkout")
@patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.has_uncommitted_changes")
@patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.get_task_checkout")
def test_cleanup_task_checkpoint_skips_dirty_checkout(
    mock_get_checkout: MagicMock,
    mock_dirty: MagicMock,
    mock_remove: MagicMock,
) -> None:
    mock_checkout = MagicMock()
    mock_checkout.path = "/tmp/task-1"
    mock_checkout.branch = "task-1/main"
    mock_get_checkout.return_value = mock_checkout
    mock_dirty.return_value = True

    result = cleanup_task_checkpoint("task-1", project_id="proj")

    assert result == {"task_id": "task-1", "status": "skipped", "reason": "dirty_checkout"}
    mock_remove.assert_not_called()


@patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.remove_task_checkout")
@patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.has_uncommitted_changes")
@patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.get_task_checkout")
def test_cleanup_task_checkpoint_removes_clean_checkout(
    mock_get_checkout: MagicMock,
    mock_dirty: MagicMock,
    mock_remove: MagicMock,
) -> None:
    mock_checkout = MagicMock()
    mock_checkout.path = "/tmp/task-1"
    mock_checkout.branch = "task-1/main"
    mock_get_checkout.return_value = mock_checkout
    mock_dirty.return_value = False
    mock_remove.return_value = True

    result = cleanup_task_checkpoint("task-1", project_id="proj")

    assert result == {
        "task_id": "task-1",
        "status": "cleaned",
        "checkout_path": "/tmp/task-1",
        "branch": "task-1/main",
        "branch_deleted": False,
    }
    mock_remove.assert_called_once_with(
        "task-1",
        delete_branch=False,
        project_id="proj",
    )
