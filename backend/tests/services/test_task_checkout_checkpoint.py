"""End-to-end coverage for the autonomous checkpoint metadata path.

Exercises ``create_checkpoint_metadata`` + ``remove_checkpoint_metadata``
against the real global checkpoint store (``~/.local/share/st/checkpoints/<project>``)
with HOME redirected to tmp_path. This guards the cf1564b8 unification:
autonomous task checkouts must now write to the same store the manual flow uses.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from app.services.task_checkout.checkpoint import (
    create_checkpoint_metadata,
    remove_checkpoint_metadata,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
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


def test_autonomous_create_then_remove_round_trips_global_store(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AGENT_ID", "autonomous-test")
    _init_repo(repo)
    monkeypatch.setattr(
        "app.services.task_checkout.checkpoint.get_project_root_path",
        lambda project_id: str(repo),
    )

    expected_meta = (
        home
        / ".local"
        / "share"
        / "st"
        / "checkpoints"
        / "summitflow"
        / "task-cp-create.meta.json"
    )

    assert create_checkpoint_metadata("task-cp-create", "summitflow", "main") is True
    assert expected_meta.exists()
    payload = json.loads(expected_meta.read_text())
    assert payload["task_id"] == "task-cp-create"
    assert payload["project_id"] == "summitflow"
    assert payload["base_branch"] == "main"
    assert payload["claimed_by"] == "autonomous-test"
    assert payload["main_repo_dirty_paths"] == []

    assert remove_checkpoint_metadata("task-cp-create", "summitflow") is True
    assert not expected_meta.exists()


def test_autonomous_create_captures_dirty_paths_baseline(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _init_repo(repo)
    (repo / "leaked.txt").write_text("dirty\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.services.task_checkout.checkpoint.get_project_root_path",
        lambda project_id: str(repo),
    )

    assert create_checkpoint_metadata("task-cp-dirty", "summitflow", "main") is True
    expected_meta = (
        home
        / ".local"
        / "share"
        / "st"
        / "checkpoints"
        / "summitflow"
        / "task-cp-dirty.meta.json"
    )
    payload = json.loads(expected_meta.read_text())
    assert payload["main_repo_dirty_paths"] == ["leaked.txt"]


def test_autonomous_create_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _init_repo(repo)
    monkeypatch.setattr(
        "app.services.task_checkout.checkpoint.get_project_root_path",
        lambda project_id: str(repo),
    )

    assert create_checkpoint_metadata("task-cp-idem", "summitflow", "main") is True
    expected_meta = (
        home
        / ".local"
        / "share"
        / "st"
        / "checkpoints"
        / "summitflow"
        / "task-cp-idem.meta.json"
    )
    first_mtime = expected_meta.stat().st_mtime_ns

    assert create_checkpoint_metadata("task-cp-idem", "summitflow", "main") is True
    assert expected_meta.stat().st_mtime_ns == first_mtime
