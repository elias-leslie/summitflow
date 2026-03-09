"""Tests for low-level merge error handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.cleanup.git_operations import merge_task_branch


@patch("app.tasks.autonomous.cleanup.git_operations.subprocess.run")
def test_merge_task_branch_reports_missing_branch(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")

    result = merge_task_branch("/tmp/project", "task-1/main", "task-1")

    assert result.success is False
    assert result.error == "Failed to merge task-1/main: branch not found"


@patch("app.tasks.autonomous.cleanup.git_operations.subprocess.run")
def test_merge_task_branch_falls_back_to_stdout_or_return_code(mock_run: MagicMock) -> None:
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="ref ok", stderr=""),
        MagicMock(returncode=1, stdout="merge blocked by local changes", stderr=""),
        MagicMock(returncode=0, stdout="", stderr=""),
    ]

    result = merge_task_branch("/tmp/project", "task-1/main", "task-1")

    assert result.success is False
    assert result.error == "Failed to merge task-1/main: merge blocked by local changes"


@patch("app.tasks.autonomous.cleanup.git_operations.subprocess.run")
def test_merge_task_branch_extracts_conflicts_from_stdout(mock_run: MagicMock) -> None:
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="ref ok", stderr=""),
        MagicMock(
            returncode=1,
            stdout=(
                "Auto-merging backend/app/services/memory/analytics_service.py\n"
                "CONFLICT (content): Merge conflict in "
                "backend/app/services/memory/analytics_service.py\n"
                "Automatic merge failed; fix conflicts and then commit the result.\n"
            ),
            stderr="",
        ),
        MagicMock(returncode=0, stdout="", stderr=""),
    ]

    result = merge_task_branch("/tmp/project", "task-1/main", "task-1")

    assert result.success is False
    assert result.conflicting_files == [
        "backend/app/services/memory/analytics_service.py"
    ]
