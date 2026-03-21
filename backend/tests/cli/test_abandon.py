"""Tests for st abandon lifecycle snapshot behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer

from cli.commands._abandon_helpers import abandon_task


def test_abandon_preview_does_not_capture_or_delete() -> None:
    client = MagicMock()

    with (
        patch("cli.commands._abandon_helpers.get_snapshot_info", return_value={"project_id": "test", "worktree_path": "/tmp/task-123"}),
        patch("cli.commands._abandon_helpers.count_unmerged_commits", return_value=0),
        patch("cli.commands._abandon_helpers.get_subtask_branches", return_value=[]),
        patch("cli.commands._abandon_helpers.get_dirty_files", return_value=[]),
        patch("cli.commands._abandon_helpers.generate_token", return_value="deadbeef"),
        patch("cli.commands._abandon_helpers.capture_lifecycle_baseline") as mock_capture,
        patch("cli.commands._abandon_helpers.remove_snapshot") as mock_remove,
        patch("cli.commands._abandon_helpers.delete_task_branches") as mock_delete,
        pytest.raises(typer.Exit) as exc,
    ):
        abandon_task(client, "task-123")

    assert exc.value.exit_code == 0
    mock_capture.assert_not_called()
    mock_remove.assert_not_called()
    mock_delete.assert_not_called()


def test_abandon_confirm_captures_before_removing_snapshot() -> None:
    client = MagicMock()
    order: list[str] = []

    def _capture(**kwargs):
        order.append("capture")
        return None

    def _remove(*args, **kwargs):
        order.append("remove")
        return True

    def _delete(*args, **kwargs):
        order.append("delete")
        return True

    with (
        patch("cli.commands._abandon_helpers.get_snapshot_info", return_value={"project_id": "test", "worktree_path": "/tmp/task-123"}),
        patch("cli.commands._abandon_helpers.count_unmerged_commits", return_value=2),
        patch("cli.commands._abandon_helpers.get_subtask_branches", return_value=["task-123/1.1"]),
        patch("cli.commands._abandon_helpers.get_dirty_files", return_value=["foo.py"]),
        patch("cli.commands._abandon_helpers.validate_token", return_value=True),
        patch("cli.commands._abandon_helpers.capture_lifecycle_baseline", side_effect=_capture) as mock_capture,
        patch("cli.commands._abandon_helpers.remove_snapshot", side_effect=_remove) as mock_remove,
        patch("cli.commands._abandon_helpers.delete_task_branches", side_effect=_delete) as mock_delete,
    ):
        result = abandon_task(client, "task-123", confirm="deadbeef")

    client.update_status.assert_called_once_with("task-123", "cancelled")
    mock_capture.assert_called_once_with(project_id="test", cwd="/tmp/task-123")
    mock_remove.assert_called_once_with("task-123", remove_worktree=True, project_id="test")
    mock_delete.assert_called_once_with("task-123")
    assert order == ["capture", "remove", "delete"]
    assert result["snapshot_removed"] is True
