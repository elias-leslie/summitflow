"""Shared base-branch helpers for git-backed task workflows."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_BASE_BRANCH_CANDIDATES = ("main", "master", "develop")
_INVALID_BASE_BRANCHES = {"", "HEAD"}
_TASK_BRANCH_RE = re.compile(r"^(?:task/)?task-[0-9a-f]{8}(?:/main)?$")


def _run_git(args: list[str], repo_path: str | Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )


def current_branch(repo_path: str | Path | None = None) -> str | None:
    """Return symbolic current branch, or None for detached/JJ colocated HEAD."""
    result = _run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], repo_path)
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch if branch and branch not in _INVALID_BASE_BRANCHES else None


def detect_base_branch(repo_path: str | Path | None = None) -> str:
    """Return repo base branch without leaking detached HEAD into task metadata."""
    for candidate in _BASE_BRANCH_CANDIDATES:
        if _run_git(["show-ref", "--verify", f"refs/heads/{candidate}"], repo_path).returncode == 0:
            return candidate
        if _run_git(["show-ref", "--verify", f"refs/remotes/origin/{candidate}"], repo_path).returncode == 0:
            return candidate

    origin_head = _run_git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], repo_path)
    if origin_head.returncode == 0:
        ref = origin_head.stdout.strip()
        if ref.startswith("origin/"):
            return ref.removeprefix("origin/")
        if ref and ref not in _INVALID_BASE_BRANCHES:
            return ref

    return current_branch(repo_path) or "main"


def normalize_base_branch(base_branch: str | None, repo_path: str | Path | None = None) -> str:
    """Replace invalid task base refs like HEAD with the repo's real base branch."""
    branch = str(base_branch or "").strip()
    return detect_base_branch(repo_path) if branch in _INVALID_BASE_BRANCHES or _TASK_BRANCH_RE.match(branch) else branch


def current_branch_or_base(repo_path: str | Path | None = None) -> str:
    """Return current symbolic branch, falling back to the detected base branch."""
    return normalize_base_branch(current_branch(repo_path), repo_path)
