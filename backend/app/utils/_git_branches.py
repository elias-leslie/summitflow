"""Git branch and worktree helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api.models.git_models import BranchInfo, WorktreeInfo

from ._git_core import WORKTREES_BASE_DIR, is_valid_git_repo, run_git

_BASE_BRANCH_CANDIDATES = ["main", "master", "develop"]


def extract_task_id_from_branch(branch_name: str) -> str | None:
    """Extract task ID from branch name if it follows task-xxx pattern."""
    match = re.match(r"^(task-[a-zA-Z0-9_-]+)(?:/.*)?$", branch_name)
    return match.group(1) if match else None


def get_branch_commit_info(branch_name: str, repo_path: Path) -> tuple[str | None, str | None]:
    """Get the last commit short hash and date for a branch."""
    result = run_git(["log", "-1", "--format=%h|%cI", branch_name], repo_path)
    if result.returncode != 0:
        return (None, None)
    parts = result.stdout.strip().split("|")
    return (parts[0], parts[1]) if len(parts) == 2 else (None, None)


def get_worktree_branches() -> dict[str, str]:
    """Get a mapping of branch names to worktree paths."""
    worktree_branches: dict[str, str] = {}
    if not WORKTREES_BASE_DIR.exists():
        return worktree_branches
    for entry in WORKTREES_BASE_DIR.iterdir():
        if not entry.is_dir() or not (entry / ".git").exists():
            continue
        result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], entry)
        if result.returncode == 0:
            worktree_branches[result.stdout.strip()] = str(entry)
    return worktree_branches


def get_all_branches(repo_path: Path) -> list[BranchInfo]:
    """Get list of all local branches with worktree indicators."""
    from ..api.models.git_models import (
        BranchInfo,
    )

    worktree_branches = get_worktree_branches()

    cr = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    current_branch = cr.stdout.strip() if cr.returncode == 0 else ""

    br = run_git(["branch", "--format=%(refname:short)"], repo_path)
    if br.returncode != 0:
        return []

    seen: set[str] = set()
    branches: list[BranchInfo] = []
    for line in br.stdout.strip().split("\n"):
        name = line.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        commit_short, commit_date = get_branch_commit_info(name, repo_path)
        branches.append(BranchInfo(
            name=name,
            is_current=name == current_branch,
            has_worktree=name in worktree_branches,
            worktree_path=worktree_branches.get(name),
            task_id=extract_task_id_from_branch(name),
            last_commit_short=commit_short,
            last_commit_date=commit_date,
        ))

    branches.sort(key=lambda b: (not b.is_current, not b.has_worktree, b.name.lower()))
    return branches


def get_worktree_info(task_id: str) -> WorktreeInfo | None:
    """Get information about an existing worktree."""
    from ..api.models.git_models import (
        WorktreeInfo,
    )

    worktree_path = WORKTREES_BASE_DIR / task_id
    if not is_valid_git_repo(worktree_path):
        return None
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], worktree_path)
    if result.returncode != 0:
        return None
    base_branch = "main"
    for candidate in _BASE_BRANCH_CANDIDATES:
        if run_git(["rev-parse", "--verify", f"origin/{candidate}"], worktree_path).returncode == 0:
            base_branch = candidate
            break
    return WorktreeInfo(
        task_id=task_id,
        path=str(worktree_path),
        branch=result.stdout.strip(),
        base_branch=base_branch,
        is_active=True,
    )
