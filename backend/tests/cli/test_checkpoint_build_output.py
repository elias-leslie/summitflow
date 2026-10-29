"""A checkpoint in a repo without .gitignore must not commit untracked build output."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cli.lib import commit_workflow

_SCOPES: list[list[str]] = []


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "app.py").write_text("before\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    (tmp_path / "app.py").write_text("after\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/new.py").write_text("new source\n")
    for artifact in ("node_modules/pkg/index.js", "dist/bundle.js", "web/node_modules/x/y.js"):
        (tmp_path / artifact).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / artifact).write_text("generated\n")
    _SCOPES.clear()
    monkeypatch.setattr(commit_workflow, "run_checks", lambda _repo, paths=(), **_kw: (_SCOPES.append(list(paths)) or True, "ok"))
    return tmp_path


def _committed(repo: Path) -> set[str]:
    return set(_git(repo, "show", "--format=", "--name-only", "HEAD").split())


def test_whole_tree_checkpoint_commits_new_source_and_skips_build_output(repo: Path) -> None:
    result = commit_workflow.commit_git_revision(repo, message="checkpoint")

    assert result["status"] == "SUCCESS"
    assert _committed(repo) == {"app.py", "src/new.py"}
    assert result["skipped_untracked"] == ["dist", "node_modules", "web/node_modules"]
    assert (repo / "node_modules/pkg/index.js").exists()
    assert _SCOPES[0] == ["app.py", "src/new.py"]


def test_directory_scope_skips_build_output_it_did_not_name(repo: Path) -> None:
    result = commit_workflow.commit_git_revision(repo, message="checkpoint", paths=["."])

    assert result["status"] == "SUCCESS"
    assert _committed(repo) == {"app.py", "src/new.py"}
    assert "node_modules" in result["skipped_untracked"]


def test_naming_a_build_output_path_commits_it(repo: Path) -> None:
    result = commit_workflow.commit_git_revision(repo, message="vendored bundle", paths=["dist/bundle.js"])

    assert result["status"] == "SUCCESS"
    assert _committed(repo) == {"dist/bundle.js"}
    assert "skipped_untracked" not in result


def test_only_build_output_dirty_commits_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "app.py").write_text("x\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules/a.js").write_text("generated\n")
    monkeypatch.setattr(commit_workflow, "run_checks", lambda *_a, **_kw: (True, "ok"))
    before = _git(tmp_path, "rev-parse", "HEAD")

    result = commit_workflow.commit_git_revision(tmp_path, message="checkpoint")

    assert result["status"] == "SKIP"
    assert result["reason"] == "only_untracked_build_output"
    assert result["skipped_untracked"] == ["node_modules"]
    assert _git(tmp_path, "rev-parse", "HEAD") == before


def test_directory_with_tracked_files_is_not_treated_as_build_output(repo: Path) -> None:
    _git(repo, "add", "-f", "dist/bundle.js")
    _git(repo, "commit", "-qm", "dist is committed on purpose")
    (repo / "dist/bundle.js").write_text("changed\n")
    (repo / "dist/extra.js").write_text("new\n")

    result = commit_workflow.commit_git_revision(repo, message="update dist")

    assert result["status"] == "SUCCESS"
    assert {"dist/bundle.js", "dist/extra.js"} <= _committed(repo)
    assert "node_modules" in result["skipped_untracked"]
    assert "dist" not in result["skipped_untracked"]
