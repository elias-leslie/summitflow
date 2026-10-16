"""Isolated acceptance of an older commit needs only its dependency inputs to match."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cli.commands.done_task_acceptance import _bindings
from cli.lib import acceptance


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def older_commit_clone(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "user.name", "Bindings")
    _git(repo, "config", "user.email", "bindings@example.invalid")
    (repo / "uv.lock").write_text("lock = 1\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("old guidance\n", encoding="utf-8")
    (repo / ".st-check.toml").write_text("[pytest]\nworkers = 2\n", encoding="utf-8")
    (repo / "alembic" / "versions").mkdir(parents=True)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "old")
    old = _git(repo, "rev-parse", "HEAD")
    # Later commit changes gate config, guidance and adds a migration.
    (repo / ".st-check.toml").write_text('[pytest]\nworkers = 2\n\n[acceptance]\nbasis = "isolated"\n', encoding="utf-8")
    (repo / "AGENTS.md").write_text("new guidance\n", encoding="utf-8")
    (repo / "alembic" / "versions" / "0002_new.py").write_text("revision = '2'\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "later")
    source = tmp_path / "source"
    _git(tmp_path, "clone", "-q", "--no-checkout", str(repo), str(source))
    _git(source, "checkout", "-q", "--detach", old)
    return repo, source


def test_older_commit_with_different_gate_config_and_guidance_is_bindable(older_commit_clone) -> None:
    repo, source = older_commit_clone
    _bindings(repo, source)
    # The clone keeps the commit's own config; nothing is copied over it.
    assert "[acceptance]" not in (source / ".st-check.toml").read_text(encoding="utf-8")


def test_dependency_lock_drift_still_refuses(older_commit_clone) -> None:
    repo, source = older_commit_clone
    (repo / "uv.lock").write_text("lock = 2\n", encoding="utf-8")
    with pytest.raises(acceptance.AcceptanceError, match="dependency/configuration inputs differ"):
        _bindings(repo, source)
