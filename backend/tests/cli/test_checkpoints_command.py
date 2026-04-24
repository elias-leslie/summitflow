"""Tests for canonical checkpoint listing and stale metadata cleanup."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from cli.commands.checkpoints import app
from cli.commands.checkpoints_cleanup import auto_cleanup_safe_items
from cli.lib.checkpoint import get_active_checkpoints, get_stale_checkpoints

runner = CliRunner()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")


def _write_checkpoint(home: Path, project_id: str, task_id: str) -> Path:
    checkpoint_dir = home / ".local" / "share" / "st" / "checkpoints" / project_id
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    meta_path = checkpoint_dir / f"{task_id}.meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "project_id": project_id,
                "base_branch": "main",
                "created_at": "2026-03-24T06:00:00+00:00",
                "claimed_by": "Test",
            }
        ),
        encoding="utf-8",
    )
    return meta_path


@pytest.fixture
def repo_with_checkpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(repo)
    _init_repo(repo)
    monkeypatch.setattr("app.storage.projects.get_project_root_path", lambda project_id: str(repo))
    monkeypatch.setattr("cli.lib.checkpoint_branches._get_repo_cwd", lambda project_id: str(repo))
    return repo


def test_get_active_checkpoints_filters_stale_global_metadata(repo_with_checkpoints: Path) -> None:
    home = Path(os.environ["HOME"])
    _git(repo_with_checkpoints, "branch", "task-live/main")
    _write_checkpoint(home, "summitflow", "task-live")
    stale_meta = _write_checkpoint(home, "summitflow", "task-stale")

    active = get_active_checkpoints("summitflow")
    stale = get_stale_checkpoints("summitflow")

    assert [checkpoint.task_id for checkpoint in active] == ["task-live"]
    assert [checkpoint.task_id for checkpoint in stale] == ["task-stale"]
    assert stale_meta.exists()


def test_auto_cleanup_safe_items_deletes_global_stale_metadata(repo_with_checkpoints: Path) -> None:
    home = Path(os.environ["HOME"])
    stale_meta = _write_checkpoint(home, "summitflow", "task-stale")

    cleaned_meta, cleaned_sql, cleaned_branches, review = auto_cleanup_safe_items("summitflow")

    assert cleaned_meta == 1
    assert cleaned_sql == 0
    assert cleaned_branches == 0
    assert review == []
    assert not stale_meta.exists()


def test_checkpoints_command_omits_and_cleans_stale_metadata(repo_with_checkpoints: Path) -> None:
    home = Path(os.environ["HOME"])
    _git(repo_with_checkpoints, "branch", "task-live/main")
    _write_checkpoint(home, "summitflow", "task-live")
    stale_meta = _write_checkpoint(home, "summitflow", "task-stale")

    result = runner.invoke(app, ["--project", "summitflow"])

    assert result.exit_code == 0
    assert "task-live" in result.output
    assert "task-stale" not in result.output
    assert not stale_meta.exists()


def test_merge_task_branch_reports_conflict_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.storage import tasks as task_store
    from cli.lib import checkpoint_branches

    conflict_output = "\n".join(
        [
            "Auto-merging backend/app/example.py",
            "CONFLICT (content): Merge conflict in backend/app/example.py",
            "Automatic merge failed; fix conflicts and then commit the result.",
        ]
    )

    def fake_run_git(
        args: list[str],
        cwd: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["git", "merge"] and "--abort" not in args:
            raise subprocess.CalledProcessError(1, args, output=conflict_output, stderr="")
        if args == ["git", "diff", "--name-only", "--diff-filter=U"]:
            return subprocess.CompletedProcess(args, 0, stdout="backend/app/example.py\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(task_store, "get_task", lambda task_id: {"status": "running"})
    monkeypatch.setattr(
        checkpoint_branches,
        "load_snapshot_meta",
        lambda task_id: SimpleNamespace(project_id="summitflow", base_branch="main"),
    )
    monkeypatch.setattr(checkpoint_branches, "_get_repo_cwd", lambda project_id: "/repo")
    monkeypatch.setattr(checkpoint_branches, "_get_current_branch", lambda cwd: "main")
    monkeypatch.setattr(checkpoint_branches, "_run_git", fake_run_git)

    with pytest.raises(SystemExit) as exc_info:
        checkpoint_branches.merge_task_branch("task-1", project_id="summitflow")

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "Failed to merge task-1/main" in stderr
    assert "backend/app/example.py" in stderr
    assert "Recovery: st git resolve-conflict task-1" in stderr
