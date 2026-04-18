"""Git branch and worktree helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api.models.git_models import BranchInfo, WorktreeInfo

from ._git_core import _resolve_project_id, run_git

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


def _get_active_worktrees(project_id: str | None = None) -> list:
    """Load active worktrees from the CLI source of truth."""
    from cli.lib.worktree import get_active_worktrees

    return get_active_worktrees(project_id)


def get_worktree_branches(
    project_id: str | None = None,
    *,
    active_worktrees: list | None = None,
) -> dict[str, str]:
    """Get a mapping of branch names to worktree paths."""
    worktrees = active_worktrees if active_worktrees is not None else _get_active_worktrees(project_id)
    return {wt.branch: str(wt.path) for wt in worktrees}


def get_all_branches(
    repo_path: Path,
    project_id: str | None = None,
    *,
    active_worktrees: list | None = None,
) -> list[BranchInfo]:
    """Get list of all local branches with worktree indicators."""
    from ..api.models.git_models import BranchInfo

    resolved_project_id = _resolve_project_id(repo_path, project_id)
    worktree_branches = get_worktree_branches(
        resolved_project_id,
        active_worktrees=active_worktrees,
    )

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
            repo_name=repo_path.name,
            project_id=resolved_project_id,
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


def _branch_commits_ahead(repo_path: Path, branch_name: str, base_branch: str) -> int:
    """Return commit count ahead of base for a branch."""
    result = run_git(["rev-list", "--count", f"{base_branch}..{branch_name}"], repo_path)
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip() or "0")
    except ValueError:
        return 0


def _branch_diff_paths(repo_path: Path, branch_name: str, base_branch: str) -> list[str]:
    """Return changed paths between base and branch."""
    result = run_git(["diff", "--name-only", base_branch, branch_name], repo_path)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def prune_worktree_registrations(repo_path: Path) -> None:
    """Prune stale git worktree registrations for a repository."""
    run_git(["worktree", "prune"], repo_path)


def get_worktree_info(task_id: str) -> WorktreeInfo | None:
    """Get information about an existing worktree."""
    from cli.lib.worktree import get_active_worktrees

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


# Re-export cleanup helpers from a dedicated module to keep branch/query helpers compact.
from ._git_branch_cleanup import (  # noqa: E402
    OrphanBranchAssessment,
    assess_orphan_task_branches,
    build_repo_workspace_summary,
    list_closed_orphan_task_branches,
    list_equivalent_orphan_task_branches,
    list_prunable_task_branches,
    prune_closed_orphan_task_branches,
    prune_equivalent_orphan_task_branches,
    prune_prunable_task_branches,
)

__all__ = [
    "OrphanBranchAssessment",
    "assess_orphan_task_branches",
    "build_repo_workspace_summary",
    "extract_task_id_from_branch",
    "get_all_branches",
    "get_branch_commit_info",
    "get_worktree_branches",
    "get_worktree_info",
    "list_closed_orphan_task_branches",
    "list_equivalent_orphan_task_branches",
    "list_prunable_task_branches",
    "prune_closed_orphan_task_branches",
    "prune_equivalent_orphan_task_branches",
    "prune_prunable_task_branches",
    "prune_worktree_registrations",
]
