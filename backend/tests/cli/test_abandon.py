from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from cli.commands._abandon_helpers import _build_preview_lines, abandon_subtask
from cli.lib.checkpoint_branches import delete_task_branches


def test_abandon_preview_does_not_claim_direct_main_has_task_branch() -> None:
    lines = _build_preview_lines(
        "task-123",
        legacy_local_branches=[],
        remote_branches=[],
        has_snapshot=True,
        snapshot_info={"project_id": "summitflow"},
        unmerged=0,
        dirty_files=[],
    )

    preview = "\n".join(lines)
    assert "Delete branch: task-123/main" not in preview
    assert "Remove checkpoint metadata" in preview
    assert "Task metadata is append-only" in preview


def test_abandon_subtask_no_longer_requires_legacy_branch() -> None:
    client = MagicMock()

    with (
        patch("cli.commands._abandon_helpers.check_branch_exists", return_value=False),
        patch("cli.commands._abandon_helpers.delete_subtask_branch") as mock_delete,
    ):
        result = abandon_subtask(client, "1.1", "task-123")

    client.update_subtask.assert_called_once_with("task-123", "1.1", passes=False)
    mock_delete.assert_not_called()
    assert result["branch_deleted"] is None


def test_delete_task_branches_does_not_switch_head() -> None:
    calls: list[list[str]] = []

    def fake_run_git(
        args: list[str],
        cwd: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check
        calls.append(args)
        if args[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return subprocess.CompletedProcess(args, 0, "main\n", "")
        if args[:3] == ["git", "branch", "--list"]:
            stdout = "  task-123/main\n" if args[-1] == "task-123/*" else ""
            return subprocess.CompletedProcess(args, 0, stdout, "")
        if args[:2] == ["git", "branch"] and args[2] == "-D":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["git", "for-each-ref"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    with patch("cli.lib.checkpoint_branches._run_git", side_effect=fake_run_git):
        assert delete_task_branches("task-123") is True

    assert not any(args[:2] == ["git", "checkout"] for args in calls)
