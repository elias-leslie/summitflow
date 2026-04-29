from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.lib.commit_workflow import CommitError, commit_repo
from cli.main import app

runner = CliRunner()


@patch("cli.main.log_task_event")
@patch("cli.main.commit_repo")
@patch("cli.main.current_repo")
def test_st_commit_uses_canonical_workflow_and_logs_task(
    mock_current_repo: MagicMock,
    mock_commit_repo: MagicMock,
    mock_log: MagicMock,
) -> None:
    mock_current_repo.return_value = Path("/repo")
    mock_commit_repo.return_value = {
        "repo": "repo",
        "status": "SUCCESS",
        "change_id": "change",
        "commit_id": "commit",
        "bookmark": "task/task-1",
        "operation_id": "op",
        "pushed": True,
    }

    result = runner.invoke(app, ["commit", "--message", "test", "--task", "task-1"])

    assert result.exit_code == 0
    mock_commit_repo.assert_called_once_with(
        Path("/repo"),
        message="test",
        task_id="task-1",
        push=True,
        skip_checks=False,
        paths=(),
    )
    mock_log.assert_called_once_with(
        "task-1",
        "st commit change=change commit=commit bookmark=task/task-1 op=op pushed=true",
    )
    assert "COMMIT[1]:status=SUCCESS pushed=true detail=commit" in result.stdout


def test_commit_repo_rejects_publish_with_skipped_checks(tmp_path: Path) -> None:
    with pytest.raises(CommitError, match="refusing to publish with --skip-checks"):
        commit_repo(tmp_path, message="test", push=True, skip_checks=True)


@patch("cli.main.commit_repo")
@patch("cli.main.current_repo")
def test_st_commit_forwards_selected_paths(
    mock_current_repo: MagicMock,
    mock_commit_repo: MagicMock,
) -> None:
    mock_current_repo.return_value = Path("/repo")
    mock_commit_repo.return_value = {
        "repo": "repo",
        "status": "SUCCESS",
        "change_id": "change",
        "commit_id": "commit",
        "pushed": True,
    }

    result = runner.invoke(app, ["commit", "-m", "test", "--path", "a.py", "--path", "b.py"])

    assert result.exit_code == 0
    mock_commit_repo.assert_called_once_with(
        Path("/repo"),
        message="test",
        task_id="",
        push=True,
        skip_checks=False,
        paths=("a.py", "b.py"),
    )


def test_commit_repo_rejects_selected_paths_without_jj(tmp_path: Path) -> None:
    with pytest.raises(CommitError, match="selective commit requires"):
        commit_repo(tmp_path, message="test", paths=("a.py",))
