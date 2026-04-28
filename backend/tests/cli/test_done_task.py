from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer import Exit

from cli.commands.done_lifecycle import _reconstruct_snapshot_info
from cli.commands.done_task import complete_task


def test_complete_task_missing_checkpoint_completed_task_is_idempotent_and_publishes() -> None:
    client = MagicMock()
    client.get_task.return_value = {
        "status": "completed",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=None),
        patch("cli.commands.done_task._reconstruct_snapshot_info", return_value=None),
        patch("cli.commands.done_task.is_working_tree_clean", return_value=True),
        patch("cli.commands.done_task._publish_completed_work") as mock_publish,
    ):
        result = complete_task(client, "task-123")

    mock_publish.assert_called_once_with("task-123", "summitflow")
    assert result["merged"] is False
    assert result["snapshot_removed"] is True


def test_complete_task_missing_checkpoint_failed_task_is_idempotent() -> None:
    client = MagicMock()
    client.get_task.return_value = {
        "status": "failed",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=None),
        patch("cli.commands.done_task._reconstruct_snapshot_info", return_value=None),
        patch("cli.commands.done_task.is_working_tree_clean", return_value=True),
    ):
        result = complete_task(client, "task-456")

    assert result["merged"] is False
    assert result["snapshot_removed"] is True


def test_complete_task_missing_checkpoint_pending_task_exits_with_guidance() -> None:
    client = MagicMock()
    client.get_task.return_value = {
        "status": "pending",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=None),
        patch("cli.commands.done_task._reconstruct_snapshot_info", return_value=None),
        patch("cli.commands.done_task.output_error") as mock_output,
        pytest.raises(Exit) as exc_info,
    ):
        complete_task(client, "task-789")

    assert exc_info.value.exit_code == 1
    assert "active task" in mock_output.call_args.args[0]


def test_reconstruct_snapshot_info_defaults_missing_base_branch_to_main() -> None:
    client = MagicMock()
    client.get_task.return_value = {
        "status": "pending",
        "project_id": "summitflow",
        "base_branch": "",
        "created_at": "2026-04-23T00:00:00Z",
        "claimed_by": "worker-1",
    }
    expected_snapshot = {
        "task_id": "task-1",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch(
            "cli.lib.checkpoint_branches.get_task_branches",
            return_value=[{"branch": "task-1/main", "type": "task"}],
        ),
        patch("cli.commands.done_lifecycle.save_snapshot_meta") as mock_save,
        patch("cli.commands.done_lifecycle.get_snapshot_info", return_value=expected_snapshot),
    ):
        result = _reconstruct_snapshot_info(client, "task-1")

    assert result == expected_snapshot
    assert mock_save.call_args.args[0].base_branch == "main"


def test_complete_task_diff_gate_checks_task_branch_not_current_head() -> None:
    client = MagicMock()
    client.get_subtasks.return_value = {"subtasks": []}
    client.get_task_completion_readiness.return_value = {"ready": True}
    client.get_task.return_value = {"status": "running"}
    snapshot_info = {
        "task_id": "task-1",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=snapshot_info),
        patch("cli.commands.done_task._checkpoint_repo_root", return_value="/repo"),
        patch("cli.commands.done_task.is_working_tree_clean", return_value=True),
        patch("cli.commands.done_task._task_branch_touched_frontend", return_value=False),
        patch("cli.commands.done_task.resolve_task_branch", return_value="task-1/main") as mock_resolve,
        patch("cli.commands.done_task.check_diff_gate") as mock_diff_gate,
        patch("cli.commands.done_task.merge_task_branch"),
        patch("cli.commands.done_task._capture_and_remove_snapshot"),
        patch("cli.commands.done_task._publish_completed_work"),
    ):
        mock_diff_gate.return_value = MagicMock(passed=True, summary="ok")

        complete_task(client, "task-1")

    mock_diff_gate.assert_called_once_with(
        "/repo",
        head_ref="task-1/main",
        base_ref="main",
    )
    mock_resolve.assert_called_once_with("task-1", project_id="summitflow")
