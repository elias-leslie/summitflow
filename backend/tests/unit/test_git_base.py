from __future__ import annotations

import subprocess
from pathlib import Path

from app.utils import git_base


def _completed(args: list[str], returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", *args], returncode, stdout=stdout, stderr="")


def test_run_git_uses_git_c_and_no_close_fds(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    completed = _completed(["status"], 0)

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return completed

    monkeypatch.setattr(git_base.safe_subprocess, "run", fake_run)

    assert git_base._run_git(["status"], Path("/repo")) is completed
    assert calls == [
        (
            ["git", "-C", "/repo", "status"],
            {
                "capture_output": True,
                "text": True,
                "check": False,
            },
        )
    ]


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


def test_normalize_base_branch_replaces_task_branch_with_detected_main(monkeypatch) -> None:
    def fake_run_git(args: list[str], repo_path=None) -> subprocess.CompletedProcess[str]:
        if args == ["show-ref", "--verify", "refs/heads/main"]:
            return _completed(args, 0)
        return _completed(args, 1)

    monkeypatch.setattr(git_base, "_run_git", fake_run_git)

    assert git_base.normalize_base_branch("task-609864c5/main", Path("/repo")) == "main"
    assert git_base.normalize_base_branch("task/task-609864c5", Path("/repo")) == "main"
    assert git_base.normalize_base_branch("task-609864c5a40b7192/main", Path("/repo")) == "main"
    assert git_base.normalize_base_branch("task/task-609864c5a40b7192", Path("/repo")) == "main"


def test_current_branch_or_base_replaces_task_branch_with_detected_main(monkeypatch) -> None:
    def fake_run_git(args: list[str], repo_path=None) -> subprocess.CompletedProcess[str]:
        if args == ["symbolic-ref", "--quiet", "--short", "HEAD"]:
            return _completed(args, 0, "task-609864c5/main\n")
        if args == ["show-ref", "--verify", "refs/heads/main"]:
            return _completed(args, 0)
        return _completed(args, 1)

    monkeypatch.setattr(git_base, "_run_git", fake_run_git)

    assert git_base.current_branch_or_base(Path("/repo")) == "main"


def test_detect_base_branch_uses_origin_head_when_candidates_missing(monkeypatch) -> None:
    def fake_run_git(args: list[str], repo_path=None) -> subprocess.CompletedProcess[str]:
        if args == ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]:
            return _completed(args, 0, "origin/develop\n")
        return _completed(args, 1)

    monkeypatch.setattr(git_base, "_run_git", fake_run_git)

    assert git_base.detect_base_branch(Path("/repo")) == "develop"
