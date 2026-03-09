"""Git branch and worktree helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api.models.git_models import BranchInfo, RepoWorkspaceSummary, WorktreeInfo

from ._git_core import run_git

_BASE_BRANCH_CANDIDATES = ["main", "master", "develop"]
_CLOSED_TASK_STATUSES = frozenset({"completed", "cancelled", "abandoned"})
_REVIEW_TASK_STATUSES = frozenset({"running", "pending", "queue", "blocked", "failed"})


@dataclass(frozen=True)
class OrphanBranchAssessment:
    """Classification result for an orphan task branch."""

    branch_name: str
    task_id: str
    resolution: str
    task_status: str | None
    commits_ahead: int
    files_changed: int
    has_node_modules_artifact: bool


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
    from cli.lib.worktree import get_active_worktrees

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


def list_prunable_task_branches(repo_path: Path) -> list[str]:
    """Return orphan task branches that are already merged into the base branch."""
    branches = get_all_branches(repo_path)
    task_branches = [branch for branch in branches if branch.task_id]
    orphan_branches = [branch for branch in task_branches if not branch.has_worktree]
    merged_branches = _get_merged_branches(repo_path, _detect_base_branch(repo_path))
    return [branch.name for branch in orphan_branches if branch.name in merged_branches]


def prune_prunable_task_branches(repo_path: Path) -> list[str]:
    """Delete merged orphan task branches and return the ones removed."""
    removed: list[str] = []
    for branch_name in list_prunable_task_branches(repo_path):
        result = run_git(["branch", "-d", branch_name], repo_path)
        if result.returncode == 0:
            removed.append(branch_name)
    return removed


def list_equivalent_orphan_task_branches(repo_path: Path) -> list[str]:
    """Return orphan task branches whose tree matches the base branch exactly."""
    branches = get_all_branches(repo_path)
    base_branch = _detect_base_branch(repo_path)
    equivalent: list[str] = []
    for branch in branches:
        if not branch.task_id or branch.has_worktree:
            continue
        if not _branch_diff_paths(repo_path, branch.name, base_branch):
            equivalent.append(branch.name)
    return equivalent


def prune_equivalent_orphan_task_branches(repo_path: Path) -> list[str]:
    """Delete orphan task branches whose tree matches base exactly."""
    removed: list[str] = []
    base_branch = _detect_base_branch(repo_path)
    current_branch_result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    current_branch = current_branch_result.stdout.strip() if current_branch_result.returncode == 0 else ""
    for branch_name in list_equivalent_orphan_task_branches(repo_path):
        if current_branch == branch_name:
            checkout_result = run_git(["checkout", base_branch], repo_path)
            if checkout_result.returncode != 0:
                continue
            current_branch = base_branch
        result = run_git(["branch", "-D", branch_name], repo_path)
        if result.returncode == 0:
            removed.append(branch_name)
    return removed


def list_closed_orphan_task_branches(repo_path: Path) -> list[str]:
    """Return orphan task branches whose linked task is already terminal."""
    from app.storage import tasks as task_store

    branches = get_all_branches(repo_path)
    closed_branches: list[str] = []
    for branch in branches:
        if not branch.task_id or branch.has_worktree:
            continue
        task = task_store.get_task(branch.task_id)
        if task and task.get("status") in _CLOSED_TASK_STATUSES:
            closed_branches.append(branch.name)
    return closed_branches


def prune_closed_orphan_task_branches(repo_path: Path) -> list[str]:
    """Delete orphan task branches when the linked task is already closed."""
    removed: list[str] = []
    base_branch = _detect_base_branch(repo_path)
    current_branch_result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    current_branch = current_branch_result.stdout.strip() if current_branch_result.returncode == 0 else ""

    for branch_name in list_closed_orphan_task_branches(repo_path):
        if current_branch == branch_name:
            checkout_result = run_git(["checkout", base_branch], repo_path)
            if checkout_result.returncode != 0:
                continue
            current_branch = base_branch
        result = run_git(["branch", "-D", branch_name], repo_path)
        if result.returncode == 0:
            removed.append(branch_name)
    return removed


def assess_orphan_task_branches(repo_path: Path) -> list[OrphanBranchAssessment]:
    """Classify orphan task branches that still need resolution."""
    from app.storage import tasks as task_store

    assessments: list[OrphanBranchAssessment] = []
    base_branch = _detect_base_branch(repo_path)
    merged_branch_names = _get_merged_branches(repo_path, base_branch)
    equivalent_branch_names = set(list_equivalent_orphan_task_branches(repo_path))

    for branch in get_all_branches(repo_path):
        if not branch.task_id or branch.has_worktree:
            continue
        if branch.name in merged_branch_names or branch.name in equivalent_branch_names:
            continue

        diff_paths = _branch_diff_paths(repo_path, branch.name, base_branch)
        task = task_store.get_task(branch.task_id)
        task_status = task.get("status") if task else None
        has_node_modules_artifact = any(path == "node_modules" or path.startswith("node_modules/") for path in diff_paths)

        if task is None:
            resolution = "salvage"
        elif task_status in _REVIEW_TASK_STATUSES:
            resolution = "review"
        elif task_status in _CLOSED_TASK_STATUSES:
            resolution = "salvage"
        else:
            resolution = "review"

        assessments.append(
            OrphanBranchAssessment(
                branch_name=branch.name,
                task_id=branch.task_id,
                resolution=resolution,
                task_status=task_status,
                commits_ahead=_branch_commits_ahead(repo_path, branch.name, base_branch),
                files_changed=len(diff_paths),
                has_node_modules_artifact=has_node_modules_artifact,
            )
        )
    return assessments


def build_repo_workspace_summary(repo_path: Path) -> RepoWorkspaceSummary:
    """Build per-repository branch/worktree cleanup counters."""
    from ..api.models.git_models import RepoWorkspaceSummary

    project_id = _get_repo_project_id(repo_path)
    branches = get_all_branches(repo_path)
    active_worktrees = _get_active_worktrees(project_id) if project_id else []
    task_branches = [branch for branch in branches if branch.task_id]
    orphan_branches = [branch for branch in task_branches if not branch.has_worktree]
    prunable_branch_names = set(list_prunable_task_branches(repo_path))
    prunable_branches = [
        branch for branch in orphan_branches if branch.name in prunable_branch_names
    ]
    orphan_assessments = assess_orphan_task_branches(repo_path)

    return RepoWorkspaceSummary(
        active_worktrees=len(active_worktrees),
        branches_with_worktrees=sum(1 for branch in task_branches if branch.has_worktree),
        task_branches=len(task_branches),
        orphan_branches=len(orphan_branches),
        prunable_branches=len(prunable_branches),
        worktree_task_ids=[worktree.task_id for worktree in active_worktrees[:2]],
        orphan_branch_names=[branch.name for branch in orphan_branches[:5]],
        prunable_branch_names=[branch.name for branch in prunable_branches[:5]],
        salvage_task_ids=[item.task_id for item in orphan_assessments if item.resolution == "salvage"][:5],
        review_orphan_task_ids=[item.task_id for item in orphan_assessments if item.resolution == "review"][:5],
    )


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
