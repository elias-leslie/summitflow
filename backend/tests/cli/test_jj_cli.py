"""Tests for st jj commands."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from typer.testing import CliRunner

from cli.commands import jj
from cli.lib import jj as jj_lib
from cli.lib.jj import JJRepoStatus, JJRevisionInfo
from cli.output_context import OutputContext

runner = CliRunner()


def test_jj_help_lists_agent_workflows() -> None:
    result = runner.invoke(jj.app, ["--help"])

    assert result.exit_code == 0
    assert "Agents call st jj or st commit" in result.stdout
    assert "op-restore" in result.stdout
    assert "revert" in result.stdout


@patch("cli.lib.jj.subprocess.run")
@patch("cli.lib.jj.shutil.which", return_value="/bin/jj")
def test_run_jj_uses_global_noninteractive_args(_mock_which: MagicMock, mock_run: MagicMock) -> None:
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    jj_lib.run_jj(Path("/repo"), ["status"])

    command = mock_run.call_args.args[0]
    assert command[:2] == ["/bin/jj", "--no-pager"]
    assert 'ui.editor="true"' in command
    assert 'ui.paginate="never"' in command
    assert 'ui.diff-editor=":builtin"' in command
    assert command[-1] == "status"
    assert mock_run.call_args.kwargs["cwd"] == Path("/repo")


@patch("cli.lib.jj.run_jj")
def test_display_branch_uses_parent_bookmark_for_detached_empty_working_copy(
    mock_run_jj: MagicMock,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".jj").mkdir()
    mock_run_jj.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=0, stdout="\n", stderr=""),
        subprocess.CompletedProcess(args=[], returncode=0, stdout="\n", stderr=""),
        subprocess.CompletedProcess(args=[], returncode=0, stdout="main\n", stderr=""),
    ]

    assert jj_lib.display_branch(tmp_path, "HEAD") == "main"


@patch("cli.commands.jj.status_summary")
@patch("cli.commands.jj._get_managed_repos")
def test_status_prints_compact_jj_state(
    mock_repos: MagicMock,
    mock_status: MagicMock,
    tmp_path: Path,
) -> None:
    mock_repos.return_value = [tmp_path]
    mock_status.return_value = JJRepoStatus(
        repo="repo",
        path="/repo",
        branch="main",
        colocated=True,
        state="clean",
        described=False,
        conflicted=False,
        unpublished=0,
        change_id="abc",
        commit_id="def",
    )

    result = runner.invoke(jj.app, ["status"], obj=OutputContext(compact=True))

    assert result.exit_code == 0
    assert "JJ[1]" in result.stdout
    assert "jj:yes" in result.stdout
    assert "change:abc" in result.stdout


@patch("cli.commands.jj.run_jj")
@patch("cli.commands.jj.current_git_repo")
def test_describe_requires_noninteractive_message(mock_repo: MagicMock, mock_run_jj: MagicMock) -> None:
    mock_repo.return_value = Path("/repo")
    mock_run_jj.return_value = MagicMock(returncode=0, stdout="", stderr="")

    result = runner.invoke(jj.app, ["describe", "-m", "test description"])

    assert result.exit_code == 0
    mock_run_jj.assert_called_once_with(Path("/repo"), ["describe", "-m", "test description"])


@patch("cli.commands.jj.log_task_event")
@patch("cli.commands.jj.publish_current_revision")
@patch("cli.commands.jj.current_git_repo")
def test_push_uses_task_bookmark_and_logs(
    mock_repo: MagicMock,
    mock_publish: MagicMock,
    mock_log: MagicMock,
) -> None:
    mock_repo.return_value = Path("/repo")
    mock_publish.return_value = {
        "repo": "repo",
        "status": "SUCCESS",
        "bookmark": "task/task-1",
        "change_id": "chg",
        "commit_id": "commit",
        "operation_id": "op",
        "pushed": True,
    }

    result = runner.invoke(jj.app, ["push", "--task", "task-1"], obj=OutputContext(compact=True))

    assert result.exit_code == 0
    mock_publish.assert_called_once_with(
        Path("/repo"),
        task_id="task-1",
        bookmark="",
        remote="origin",
        dry_run=False,
    )
    mock_log.assert_called_once()
    assert "JJPUSH:repo:SUCCESS" in result.stdout


@patch("cli.commands.jj.log_task_event")
@patch("cli.commands.jj.delete_task_bookmark")
@patch("cli.commands.jj.current_git_repo")
def test_push_delete_bookmark_cleans_task_bookmark(
    mock_repo: MagicMock,
    mock_delete: MagicMock,
    mock_log: MagicMock,
) -> None:
    mock_repo.return_value = Path("/repo")
    mock_delete.return_value = {
        "repo": "repo",
        "status": "SUCCESS",
        "bookmark": "task/task-1",
        "operation_id": "op",
        "deleted": True,
    }

    result = runner.invoke(
        jj.app,
        ["push", "--delete-bookmark", "--task", "task-1"],
        obj=OutputContext(compact=True),
    )

    assert result.exit_code == 0
    mock_delete.assert_called_once_with(
        Path("/repo"),
        task_id="task-1",
        bookmark="",
        remote="origin",
        dry_run=False,
    )
    mock_log.assert_called_once_with("task-1", "st jj push --delete-bookmark task/task-1 op=op")
    assert "JJPUSH:repo:SUCCESS:bookmark=task/task-1 deleted=true" in result.stdout


def test_publish_rejects_failed_quality_gate(tmp_path: Path) -> None:
    (tmp_path / ".jj").mkdir()
    (tmp_path / ".git").mkdir()
    revision = JJRevisionInfo(
        change_id="chg",
        commit_id="commit",
        empty=False,
        conflict=False,
        description="ready",
    )
    with (
        patch("cli.lib.jj.current_revision_info", return_value=revision),
        patch("cli.lib.jj.run_checks", return_value=(False, "boom")),
        patch("cli.lib.jj.run_jj") as mock_run_jj,
        pytest.raises(jj_lib.JJError, match="quality gates failed before jj push"),
    ):
        jj_lib.publish_current_revision(tmp_path, task_id="task-1")

    mock_run_jj.assert_not_called()


def test_publish_without_task_uses_current_bookmark(tmp_path: Path) -> None:
    (tmp_path / ".jj").mkdir()
    (tmp_path / ".git").mkdir()
    revision = JJRevisionInfo(
        change_id="chg",
        commit_id="commit",
        empty=False,
        conflict=False,
        description="ready",
    )
    with (
        patch("cli.lib.jj.current_revision_info", return_value=revision),
        patch("cli.lib.jj.run_checks", return_value=(True, "ok")),
        patch("cli.lib.jj.display_branch", return_value="main"),
        patch("cli.lib.jj.latest_operation_id", return_value="op"),
        patch("cli.lib.jj.run_jj") as mock_run_jj,
    ):
        mock_run_jj.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        result = jj_lib.publish_current_revision(tmp_path)

    assert result["bookmark"] == "main"
    assert call(tmp_path, ["bookmark", "set", "main", "-r", "@"]) in mock_run_jj.call_args_list
    assert call(
        tmp_path,
        ["git", "push", "--remote", "origin", "--bookmark", "main", "--allow-empty-description"],
    ) in mock_run_jj.call_args_list


def test_commit_rejects_skip_checks_when_publishing(tmp_path: Path) -> None:
    (tmp_path / ".jj").mkdir()
    (tmp_path / ".git").mkdir()

    with pytest.raises(jj_lib.JJError, match="refusing to publish jj revision with --skip-checks"):
        jj_lib.commit_current_revision(tmp_path, message="test", push=True, skip_checks=True)


@patch("cli.commands.jj.log_task_event")
@patch("cli.commands.jj.run_jj")
@patch("cli.commands.jj.current_git_repo")
def test_recovery_commands_log_task_events(
    mock_repo: MagicMock,
    mock_run_jj: MagicMock,
    mock_log: MagicMock,
) -> None:
    mock_repo.return_value = Path("/repo")
    mock_run_jj.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    undo = runner.invoke(jj.app, ["undo", "--task", "task-1"])
    restore = runner.invoke(jj.app, ["op-restore", "op123", "--task", "task-1"])

    assert undo.exit_code == 0
    assert restore.exit_code == 0
    assert call("task-1", "st jj undo executed") in mock_log.call_args_list
    assert call("task-1", "st jj op-restore op123 executed") in mock_log.call_args_list


@patch("cli.commands.jj.run_jj")
@patch("cli.commands.jj.current_git_repo")
def test_remote_bookmarks_lists_remote_refs_through_st_surface(
    mock_repo: MagicMock,
    mock_run_jj: MagicMock,
) -> None:
    mock_repo.return_value = Path("/repo")
    mock_run_jj.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    result = runner.invoke(jj.app, ["remote-bookmarks", "jj-smoke/repo", "--fetch"])

    assert result.exit_code == 0
    assert mock_run_jj.call_args_list == [
        call(Path("/repo"), ["git", "fetch", "--remote", "origin"]),
        call(
            Path("/repo"),
            ["bookmark", "list", "--all-remotes", "--remote", "origin", "jj-smoke/repo"],
        ),
    ]


@patch("cli.commands.jj.run_jj")
@patch("cli.commands.jj.current_git_repo")
def test_conflicts_maps_to_noninteractive_resolve_list(
    mock_repo: MagicMock,
    mock_run_jj: MagicMock,
) -> None:
    mock_repo.return_value = Path("/repo")
    mock_run_jj.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="file\n", stderr="")

    result = runner.invoke(jj.app, ["conflicts"])

    assert result.exit_code == 0
    mock_run_jj.assert_called_once_with(Path("/repo"), ["resolve", "--list"])


@patch("cli.commands.jj.run_jj")
@patch("cli.commands.jj.current_git_repo")
def test_conflicts_no_conflicts_is_success(
    mock_repo: MagicMock,
    mock_run_jj: MagicMock,
) -> None:
    mock_repo.return_value = Path("/repo")
    mock_run_jj.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=2,
        stdout="",
        stderr="Error: No conflicts found at this revision\n",
    )

    result = runner.invoke(jj.app, ["conflicts"])

    assert result.exit_code == 0
    assert "CONFLICTS[0]" in result.stdout


@patch("cli.commands.jj.log_task_event")
@patch("cli.commands.jj.publish_current_revision")
@patch("cli.commands.jj.run_jj")
@patch("cli.commands.jj.current_git_repo")
def test_revert_creates_pushed_rollback_change(
    mock_repo: MagicMock,
    mock_run_jj: MagicMock,
    mock_publish: MagicMock,
    mock_log: MagicMock,
) -> None:
    mock_repo.return_value = Path("/repo")
    mock_run_jj.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    mock_publish.return_value = {
        "repo": "repo",
        "status": "SUCCESS",
        "bookmark": "task/task-1",
        "change_id": "chg",
        "commit_id": "commit",
        "operation_id": "op",
        "pushed": True,
    }

    result = runner.invoke(
        jj.app,
        ["revert", "badrev", "--message", "rollback badrev", "--push", "--task", "task-1"],
    )

    assert result.exit_code == 0
    assert mock_run_jj.call_args_list[:2] == [
        call(Path("/repo"), ["revert", "-r", "badrev", "--onto", "@"]),
        call(Path("/repo"), ["describe", "-m", "rollback badrev"]),
    ]
    mock_publish.assert_called_once_with(Path("/repo"), task_id="task-1")
    assert call("task-1", "st jj revert badrev onto=@ executed") in mock_log.call_args_list
    assert "JJREVERT:repo:SUCCESS" in result.stdout
