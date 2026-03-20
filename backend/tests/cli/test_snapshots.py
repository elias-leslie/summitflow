"""Tests for quick snapshot CLI support."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=merged_env,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Snapshot Tester")
    _git(repo, "config", "user.email", "snapshot@test.local")
    (repo / ".index.yaml").write_text("project: summitflow\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")


def _read_index_file(repo: Path, path: str) -> str:
    return _git(repo, "show", f":{path}").stdout


def test_quick_snapshot_round_trip_restores_tracked_staged_and_untracked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.quick_snapshots import capture_snapshot, list_snapshots, restore_snapshot

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    tracked = repo / "tracked.txt"
    tracked.write_text("staged\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    tracked.write_text("worktree\n", encoding="utf-8")
    (repo / "note.txt").write_text("hello\n", encoding="utf-8")
    (repo / "ignored.log").write_text("ignored-before\n", encoding="utf-8")

    monkeypatch.chdir(repo)
    snapshot = capture_snapshot("before-refactor", project_id="summitflow")

    tracked.write_text("after\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    tracked.write_text("after-worktree\n", encoding="utf-8")
    (repo / "note.txt").unlink()
    (repo / "junk.txt").write_text("junk\n", encoding="utf-8")
    (repo / "ignored.log").write_text("ignored-after\n", encoding="utf-8")

    restored = restore_snapshot(snapshot.id, project_id="summitflow")

    assert restored.id == snapshot.id
    assert tracked.read_text(encoding="utf-8") == "worktree\n"
    assert _read_index_file(repo, "tracked.txt") == "staged\n"
    assert (repo / "note.txt").read_text(encoding="utf-8") == "hello\n"
    assert not (repo / "junk.txt").exists()

    listed = list_snapshots(project_id="summitflow")
    assert [entry.id for entry in listed] == [snapshot.id]
    assert listed[0].name == "before-refactor"


def test_quick_snapshot_restore_preserves_ignored_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib.quick_snapshots import capture_snapshot, restore_snapshot

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    ignored = repo / "ignored.log"
    ignored.write_text("v1\n", encoding="utf-8")

    monkeypatch.chdir(repo)
    snapshot = capture_snapshot("ignored-scope", project_id="summitflow")

    ignored.write_text("v2\n", encoding="utf-8")
    restore_snapshot(snapshot.id, project_id="summitflow")

    assert ignored.read_text(encoding="utf-8") == "v2\n"


def test_rollback_command_accepts_negative_index(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.commands.snapshots import app

    captured: dict[str, str] = {}

    def _fake_restore(target: str, project_id: str) -> object:
        captured["target"] = target
        captured["project_id"] = project_id
        return type("Snapshot", (), {"id": "snap-1", "name": "latest", "backend": "git-ref"})()

    monkeypatch.setenv("ST_PROJECT_ID", "summitflow")
    monkeypatch.setattr("cli.commands.snapshots.restore_snapshot", _fake_restore)

    result = runner.invoke(app, ["rollback", "-1"])

    assert result.exit_code == 0
    assert captured == {"target": "-1", "project_id": "summitflow"}
