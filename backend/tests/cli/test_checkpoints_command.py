"""Tests for canonical checkpoint listing and stale metadata cleanup."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.commands import cleanup as cleanup_cmd
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


def test_get_active_checkpoints_includes_metadata_only_claims(
    repo_with_checkpoints: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path(os.environ["HOME"])
    _write_checkpoint(home, "summitflow", "task-live")
    monkeypatch.setattr("cli.lib.checkpoint._task_status", lambda _task_id: "running")

    active = get_active_checkpoints("summitflow")

    assert [checkpoint.task_id for checkpoint in active] == ["task-live"]


def test_get_stale_checkpoints_filters_terminal_metadata(
    repo_with_checkpoints: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path(os.environ["HOME"])
    _write_checkpoint(home, "summitflow", "task-live")
    stale_meta = _write_checkpoint(home, "summitflow", "task-stale")
    monkeypatch.setattr(
        "cli.lib.checkpoint._task_status",
        lambda task_id: "completed" if task_id == "task-stale" else "running",
    )

    stale = get_stale_checkpoints("summitflow")

    assert [checkpoint.task_id for checkpoint in stale] == ["task-stale"]
    assert stale_meta.exists()


def test_auto_cleanup_safe_items_deletes_global_stale_metadata(
    repo_with_checkpoints: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path(os.environ["HOME"])
    stale_meta = _write_checkpoint(home, "summitflow", "task-stale")
    monkeypatch.setattr("cli.lib.checkpoint._task_status", lambda _task_id: "completed")

    cleaned_meta, cleaned_sql, cleaned_branches, review = auto_cleanup_safe_items("summitflow")

    assert cleaned_meta == 1
    assert cleaned_sql == 0
    assert cleaned_branches == 0
    assert review == []
    assert not stale_meta.exists()


def test_checkpoints_command_omits_and_cleans_stale_metadata(
    repo_with_checkpoints: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path(os.environ["HOME"])
    _write_checkpoint(home, "summitflow", "task-live")
    stale_meta = _write_checkpoint(home, "summitflow", "task-stale")
    monkeypatch.setattr(
        "cli.lib.checkpoint._task_status",
        lambda task_id: "completed" if task_id == "task-stale" else "running",
    )

    result = runner.invoke(app, ["--project", "summitflow"])

    assert result.exit_code == 0
    assert "task-live" in result.output
    assert "task-stale" not in result.output
    assert not stale_meta.exists()


def test_cleanup_checkpoints_auto_deletes_stale_metadata_when_no_active(
    repo_with_checkpoints: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path(os.environ["HOME"])
    stale_meta = _write_checkpoint(home, "summitflow", "task-stale")
    monkeypatch.setattr(cleanup_cmd, "get_project_id", lambda all_projects: "summitflow")
    monkeypatch.setattr(cleanup_cmd, "_iter_target_repos", lambda all_projects: [repo_with_checkpoints])
    monkeypatch.setattr("cli.lib.checkpoint._task_status", lambda _task_id: "completed")

    result = runner.invoke(cleanup_cmd.app, ["checkpoints", "--auto"])

    assert result.exit_code == 0
    assert "Pruned stale checkpoint metadata: 1" in result.output
    assert not stale_meta.exists()


def test_task_branch_resolution_supports_recovered_short_branch(
    repo_with_checkpoints: Path,
) -> None:
    from cli.lib.checkpoint_branches import get_task_branches, resolve_task_branch

    _git(repo_with_checkpoints, "branch", "task-short")

    branches = get_task_branches("task-short", project_id="summitflow")

    assert branches == [{"branch": "task-short", "subtask_id": "", "type": "task"}]
    assert resolve_task_branch("task-short", project_id="summitflow") == "task-short"
