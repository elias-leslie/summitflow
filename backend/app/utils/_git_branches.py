"""Git branch and worktree helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api.models.git_models import BranchInfo, RepoWorkspaceSummary, WorktreeInfo

from ._git_core import run_git

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


def _get_repo_project_id(repo_path: Path) -> str | None:
    """Return the project id inferred from a managed repository path."""
    project_id = repo_path.name
    return None if project_id.startswith(".") else project_id


def _get_active_worktrees(project_id: str | None = None) -> list:
    """Load active worktrees from the CLI source of truth."""
    from ...cli.lib.worktree import get_active_worktrees

    return get_active_worktrees(project_id)


def get_worktree_branches(project_id: str | None = None) -> dict[str, str]:
    """Get a mapping of branch names to worktree paths."""
    worktree_branches: dict[str, str] = {}
    for worktree in _get_active_worktrees(project_id):
        worktree_branches[worktree.branch] = str(worktree.path)
    return worktree_branches


def get_all_branches(repo_path: Path) -> list[BranchInfo]:
    """Get list of all local branches with worktree indicators."""
    from ..api.models.git_models import (
        BranchInfo,
    )

    worktree_branches = get_worktree_branches(_get_repo_project_id(repo_path))

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


def _detect_base_branch(repo_path: Path) -> str:
    """Return the most likely base branch for a repository."""
    for candidate in _BASE_BRANCH_CANDIDATES:
        if run_git(["show-ref", "--verify", f"refs/heads/{candidate}"], repo_path).returncode == 0:
            return candidate
        if run_git(["show-ref", "--verify", f"refs/remotes/origin/{candidate}"], repo_path).returncode == 0:
            return candidate
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    return result.stdout.strip() if result.returncode == 0 else "main"


def _get_merged_branches(repo_path: Path, base_branch: str) -> set[str]:
    """Return local branches already merged into the base branch."""
    result = run_git(["branch", "--format=%(refname:short)", "--merged", base_branch], repo_path)
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def build_repo_workspace_summary(repo_path: Path) -> RepoWorkspaceSummary:
    """Build per-repository branch/worktree cleanup counters."""
    from ..api.models.git_models import RepoWorkspaceSummary

    project_id = _get_repo_project_id(repo_path)
    branches = get_all_branches(repo_path)
    active_worktrees = _get_active_worktrees(project_id) if project_id else []
    task_branches = [branch for branch in branches if branch.task_id]
    orphan_branches = [branch for branch in task_branches if not branch.has_worktree]
    merged_branches = _get_merged_branches(repo_path, _detect_base_branch(repo_path))
    prunable_branches = [branch for branch in orphan_branches if branch.name in merged_branches]

    return RepoWorkspaceSummary(
        active_worktrees=len(active_worktrees),
        branches_with_worktrees=sum(1 for branch in task_branches if branch.has_worktree),
        task_branches=len(task_branches),
        orphan_branches=len(orphan_branches),
        prunable_branches=len(prunable_branches),
        worktree_task_ids=[worktree.task_id for worktree in active_worktrees[:2]],
    )


def get_worktree_info(task_id: str) -> WorktreeInfo | None:
    """Get information about an existing worktree."""
    from ...cli.lib.worktree import get_active_worktrees
    from ..api.models.git_models import WorktreeInfo

    for worktree in get_active_worktrees():
        if worktree.task_id == task_id:
            return WorktreeInfo(
                task_id=worktree.task_id,
                path=str(worktree.path),
                branch=worktree.branch,
                base_branch=worktree.base_branch,
                is_active=worktree.is_active,
                project_id=worktree.project_id,
            )
    return None
