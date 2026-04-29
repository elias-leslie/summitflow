from __future__ import annotations

import subprocess
from pathlib import Path

from app.utils import git_base


def _completed(args: list[str], returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", *args], returncode, stdout=stdout, stderr="")


def test_current_branch_returns_none_for_detached_head(monkeypatch) -> None:
    monkeypatch.setattr(git_base, "_run_git", lambda args, repo_path=None: _completed(args, 1))

    assert git_base.current_branch(Path("/repo")) is None


def test_normalize_base_branch_replaces_head_with_detected_main(monkeypatch) -> None:
    def fake_run_git(args: list[str], repo_path=None) -> subprocess.CompletedProcess[str]:
        if args == ["show-ref", "--verify", "refs/heads/main"]:
            return _completed(args, 0)
        return _completed(args, 1)

    monkeypatch.setattr(git_base, "_run_git", fake_run_git)

    assert git_base.normalize_base_branch("HEAD", Path("/repo")) == "main"


def test_detect_base_branch_uses_origin_head_when_candidates_missing(monkeypatch) -> None:
    def fake_run_git(args: list[str], repo_path=None) -> subprocess.CompletedProcess[str]:
        if args == ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]:
            return _completed(args, 0, "origin/develop\n")
        return _completed(args, 1)

    monkeypatch.setattr(git_base, "_run_git", fake_run_git)

    assert git_base.detect_base_branch(Path("/repo")) == "develop"
