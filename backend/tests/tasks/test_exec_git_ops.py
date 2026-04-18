"""Tests for autonomous execution git preservation helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


@patch("app.tasks.autonomous.exec_modules.git_ops.has_uncommitted_changes")
@patch("app.tasks.autonomous.exec_modules.git_ops.has_unpublished_commits")
@patch("app.tasks.autonomous.exec_modules.git_ops.shutil.which")
@patch("app.tasks.autonomous.exec_modules.git_ops.resolve_script")
@patch("app.tasks.autonomous.exec_modules.git_ops._run_git")
@patch("app.tasks.autonomous.exec_modules.git_ops.subprocess.run")
def test_smart_commit_uses_canonical_commit_script_with_push_and_skip_checks(
    mock_run: MagicMock,
    mock_git: MagicMock,
    mock_resolve_script: MagicMock,
    mock_which: MagicMock,
    mock_has_unpublished_commits: MagicMock,
    mock_has_uncommitted_changes: MagicMock,
) -> None:
    from app.tasks.autonomous.exec_modules.git_ops import smart_commit

    mock_resolve_script.return_value = Path("/srv/workspaces/projects/summitflow/scripts/commit.sh")
    mock_which.return_value = None
    mock_has_uncommitted_changes.return_value = True
    mock_has_unpublished_commits.return_value = False
    mock_git.side_effect = [
        MagicMock(stdout="/tmp/checkout\n", returncode=0),
    ]
    mock_run.return_value = MagicMock(returncode=0, stderr="")

    with patch("pathlib.Path.is_file", return_value=True), patch(
        "pathlib.Path.stat",
        return_value=MagicMock(st_mode=0o100755),
    ):
        result = smart_commit(
            "/tmp/checkout",
            "fix: preserve work",
            task_id="task-1",
            push=True,
            skip_checks=True,
        )

    assert result
    mock_run.assert_called_once_with(
        [
            "/tmp/checkout/scripts/commit.sh",
            "--json",
            "--current",
            "--msg",
            "fix: preserve work",
            "--task",
            "task-1",
            "--push",
            "--skip-checks",
        ],
        cwd="/tmp/checkout",
        capture_output=True,
        text=True,
        timeout=300,
    )


@patch("app.tasks.autonomous.exec_modules.git_ops.shutil.which")
@patch("app.tasks.autonomous.exec_modules.git_ops._resolve_commit_script")
@patch("app.tasks.autonomous.exec_modules.git_ops.subprocess.run")
def test_publish_existing_commits_pushes_clean_ahead_branch(
    mock_run: MagicMock,
    mock_resolve_commit_script: MagicMock,
    mock_which: MagicMock,
) -> None:
    from app.tasks.autonomous.exec_modules.git_ops import publish_existing_commits

    mock_which.return_value = None
    mock_resolve_commit_script.return_value = "/tmp/checkout/scripts/commit.sh"
    mock_run.return_value = MagicMock(returncode=0, stderr="")

    with patch(
        "app.tasks.autonomous.exec_modules.git_ops.has_unpublished_commits",
        side_effect=[True, False],
    ):
        result = publish_existing_commits("/tmp/checkout")

    assert result
    mock_run.assert_called_once_with(
        ["/tmp/checkout/scripts/commit.sh", "--json", "--current", "--push"],
        cwd="/tmp/checkout",
        capture_output=True,
        text=True,
        timeout=300,
    )
