from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.lib import jj
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
        bookmark="",
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


def test_commit_repo_prunes_safe_residue_after_publish(tmp_path: Path) -> None:
    (tmp_path / ".jj").mkdir()
    (tmp_path / ".git").mkdir()
    with (
        patch(
            "cli.lib.commit_workflow.commit_current_revision",
            return_value={"repo": "repo", "status": "SUCCESS", "pushed": True},
        ),
        patch(
            "cli.commands.cleanup_handlers.cleanup_safe_git_residue",
            return_value=(0, 0, 0, 0, 1, 2),
        ) as cleanup,
    ):
        result = commit_repo(tmp_path, message="test", push=True)

    cleanup.assert_called_once_with([tmp_path], dry_run=False)
    assert result["residue_pruned"] == 3
    assert result["residue_pruned_counts"]["task_local"] == 1
    assert result["residue_pruned_counts"]["task_remote"] == 2


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
        bookmark="",
        paths=("a.py", "b.py"),
    )


@patch("cli.main.commit_repo")
@patch("cli.main.current_repo")
def test_st_commit_forwards_explicit_bookmark(
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

    result = runner.invoke(app, ["commit", "-m", "test", "--bookmark", "main"])

    assert result.exit_code == 0
    mock_commit_repo.assert_called_once_with(
        Path("/repo"),
        message="test",
        task_id="",
        push=True,
        skip_checks=False,
        bookmark="main",
        paths=(),
    )


def test_commit_repo_skips_gitignored_paths_in_add_step(tmp_path: Path) -> None:
    """Already-ignored paths (e.g., user did `git rm --cached` then added to .gitignore)
    must not abort the commit. The add step should skip them; commit picks up the
    pre-staged deletion."""
    from cli.lib import commit_workflow

    (tmp_path / ".git").mkdir()

    def fake_run_git(_repo: Path, args: list[str]):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        if args[:2] == ["status", "--porcelain"]:
            result.stdout = "D  ignored.json\nM  .gitignore\n"
        if args[:2] == ["diff", "--cached"] and "--quiet" in args:
            result.returncode = 1
        if args[:1] == ["check-ignore"]:
            # ignored.json is gitignored; .gitignore itself isn't.
            result.returncode = 0 if "ignored.json" in args else 1
        if args[:2] == ["rev-parse", "--short"]:
            result.stdout = "abc1234"
        return result

    with (
        patch.object(commit_workflow, "run_git", side_effect=fake_run_git) as run,
        patch.object(commit_workflow, "run_checks", return_value=(True, "")),
    ):
        result = commit_repo(
            tmp_path,
            message="ignore drift",
            paths=(".gitignore", "ignored.json"),
            push=False,
        )

    add_calls = [c for c in run.call_args_list if c.args[1][:1] == ["add"]]
    assert add_calls, "expected git add to be called for the non-ignored path"
    # ignored.json must be excluded from add args
    assert add_calls[0].args[1] == ["add", "--", ".gitignore"]
    assert result["status"] == "SUCCESS"

    def fake_run_git(_repo: Path, args: list[str]):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        if args[:2] == ["status", "--porcelain"]:
            result.stdout = " M a.py\n"
        if args[:2] == ["diff", "--cached"] and "--quiet" in args:
            result.returncode = 1  # has staged changes
        if args[:1] == ["check-ignore"]:
            # default: not ignored (exit 1 means no match)
            result.returncode = 1
        if args[:2] == ["rev-parse", "--short"]:
            result.stdout = "abc1234"
        if args[:1] == ["push"]:
            result.stdout = "pushed"
        return result

    with (
        patch.object(commit_workflow, "run_git", side_effect=fake_run_git) as run,
        patch.object(commit_workflow, "run_checks", return_value=(True, "")),
        patch(
            "cli.commands.cleanup_handlers.cleanup_safe_git_residue",
            return_value=(0, 0, 0, 0, 0, 0),
        ),
    ):
        result = commit_repo(tmp_path, message="scoped", paths=("a.py",), push=True)

    assert result["status"] == "SUCCESS"
    assert result["selected_paths"] == ["a.py"]
    add_calls = [c for c in run.call_args_list if c.args[1][:1] == ["add"]]
    assert add_calls, "expected git add to be called"
    assert add_calls[0].args[1] == ["add", "--", "a.py"], "git add must be scoped, not -A"


def test_jj_run_checks_scopes_changed_files_for_selected_paths(tmp_path: Path) -> None:
    with patch("cli.lib.jj.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""

        ok, detail = jj.run_checks(tmp_path, paths=("frontend/a.tsx", "backend/b.py"))

    assert ok is True
    assert detail == "ok"
    env = run.call_args.kwargs["env"]
    assert env["ST_CHECK_CHANGED_FILES"] == "frontend/a.tsx\nbackend/b.py"
