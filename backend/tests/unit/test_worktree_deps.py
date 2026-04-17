"""Tests for worktree dependency symlinking."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _init_git_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)


def test_symlink_gitignored_deps_links_backend_venv_into_lane(tmp_path: Path) -> None:
    from cli.lib.worktree_deps import symlink_gitignored_deps

    repo_root = tmp_path / "projects" / "summitflow"
    lane_root = tmp_path / "lanes" / "summitflow" / "task-1"
    backend_venv = repo_root / "backend" / ".venv"

    (repo_root / "backend").mkdir(parents=True)
    backend_venv.mkdir()
    (backend_venv / "bin").mkdir()
    (backend_venv / "bin" / "python").write_text("#!/usr/bin/env python\n", encoding="utf-8")
    (repo_root / ".gitignore").write_text("backend/.venv\n", encoding="utf-8")
    lane_root.mkdir(parents=True)
    (lane_root / "backend").mkdir()
    _init_git_repo(repo_root)

    symlink_gitignored_deps(repo_root, lane_root)

    lane_venv = lane_root / "backend" / ".venv"
    assert lane_venv.is_symlink()
    assert lane_venv.resolve() == backend_venv.resolve()
    exclude_file = lane_root / ".git" / "info" / "exclude"
    assert "backend/.venv" in exclude_file.read_text(encoding="utf-8")
