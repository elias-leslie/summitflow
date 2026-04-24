"""Tests for canonical checkpoint listing and stale metadata cleanup."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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

    recorded_fields: dict[str, Any] = {}
    status_updates: list[tuple[str, str, str | None, bool]] = []
    events: list[tuple[str, str]] = []

    def record_status_update(
        task_id: str,
        status: str,
        error_message: str | None = None,
        validate_transition: bool = True,
    ) -> None:
        status_updates.append((task_id, status, error_message, validate_transition))

    monkeypatch.setattr(task_store, "get_task", lambda task_id: {"status": "running"})
    monkeypatch.setattr(
        "app.storage.tasks.update.update_task_fields",
        lambda task_id, **fields: recorded_fields.update(fields),
    )
    monkeypatch.setattr(
        "app.storage.tasks.status.update_task_status",
        record_status_update,
    )
    monkeypatch.setattr(
        "app.storage.log_task_event",
        lambda task_id, message: events.append((task_id, message)),
    )
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
    assert recorded_fields["conflict_info"]["conflicting_files"] == ["backend/app/example.py"]
    assert status_updates == [("task-1", "failed", "Merge conflict in 1 file(s)", False)]
    assert events == [
        ("task-1", "Merge conflict detected in 1 file(s): backend/app/example.py")
    ]


def test_task_branch_resolution_supports_recovered_short_branch(
    repo_with_checkpoints: Path,
) -> None:
    from cli.lib.checkpoint_branches import get_task_branches, resolve_task_branch

    _git(repo_with_checkpoints, "branch", "task-short")

    branches = get_task_branches("task-short", project_id="summitflow")

    assert branches == [{"branch": "task-short", "subtask_id": "", "type": "task"}]
    assert resolve_task_branch("task-short", project_id="summitflow") == "task-short"


def test_merge_task_branch_uses_recovered_short_branch(
    repo_with_checkpoints: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.storage import tasks as task_store
    from cli.lib import checkpoint_branches

    _git(repo_with_checkpoints, "branch", "task-short")
    monkeypatch.setattr(task_store, "get_task", lambda task_id: {"status": "running"})
    monkeypatch.setattr(
        checkpoint_branches,
        "load_snapshot_meta",
        lambda task_id: SimpleNamespace(project_id="summitflow", base_branch="main"),
    )

    assert checkpoint_branches.merge_task_branch("task-short", project_id="summitflow")
    assert _git(repo_with_checkpoints, "branch", "--list", "task-short").stdout == ""
