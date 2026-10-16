"""A receipt stays valid for its commit across host drift that cannot change the gate outcome."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cli.lib import acceptance


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def _passing(command: list[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, "ok", "")


@pytest.fixture
def accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, local_gate_tools: None) -> tuple[Path, Path, dict]:
    home = tmp_path.parent / f"{tmp_path.name}-home"
    home.mkdir()
    (home / ".env.local").write_text("OTHER_PROJECT_KEY=one\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "user.name", "Drift")
    _git(repo, "config", "user.email", "drift@example.invalid")
    (repo / ".gitignore").write_text(".env.local\n", encoding="utf-8")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "old.py").write_text("gone = True\n", encoding="utf-8")
    (repo / ".st-check.toml").write_text("[pytest]\nworkers = 2\n", encoding="utf-8")
    (repo / ".env.local").write_text("FEATURE_FLAG=on\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "app.py", "old.py", ".st-check.toml")
    _git(repo, "commit", "-qm", "initial")
    receipt = acceptance.accept_revision(repo, sha="HEAD", runner=_passing)
    return repo, home, receipt


def test_in_place_receipt_survives_later_commits_wip_home_env_and_metadata(accepted) -> None:
    repo, home, receipt = accepted
    commit = receipt["source_commit"]
    # Another project's key in the shared home env file.
    (home / ".env.local").write_text("OTHER_PROJECT_KEY=two\n", encoding="utf-8")
    # Later work: the tracked gate config changes, a file is deleted, a file is renamed.
    (repo / ".st-check.toml").write_text('[pytest]\nworkers = 2\n\n[acceptance]\nbasis = "isolated"\n', encoding="utf-8")
    _git(repo, "rm", "-q", "old.py")
    _git(repo, "commit", "-qam", "later")
    # Another agent's uncommitted edit and a permission-only change of a local env file.
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    (repo / ".env.local").chmod(0o600)

    validated = acceptance.validate_acceptance_receipt(repo, Path(receipt["acceptance_artifact"]), sha=commit)
    assert validated["source_commit"] == commit


def test_receipt_still_binds_the_untracked_project_env_content(accepted) -> None:
    repo, _home, receipt = accepted
    (repo / ".env.local").write_text("FEATURE_FLAG=off\n", encoding="utf-8")
    with pytest.raises(acceptance.AcceptanceError, match="local environment/configuration inputs no longer match"):
        acceptance.validate_acceptance_receipt(repo, Path(receipt["acceptance_artifact"]), sha=receipt["source_commit"])


def test_in_place_receipt_for_head_survives_another_agents_uncommitted_work(accepted) -> None:
    repo, _home, receipt = accepted
    (repo / "app.py").write_text("value = 3\n", encoding="utf-8")
    (repo / "new_wip.py").write_text("draft = True\n", encoding="utf-8")
    validated = acceptance.validate_acceptance_receipt(repo, Path(receipt["acceptance_artifact"]), sha="HEAD")
    assert validated["source_commit"] == receipt["source_commit"]
