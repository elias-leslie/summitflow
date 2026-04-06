"""Git branch and worktree helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api.models.git_models import BranchInfo, RepoWorkspaceSummary, WorktreeInfo

from ._git_core import _resolve_project_id, run_git

_BASE_BRANCH_CANDIDATES = ["main", "master", "develop"]
_CLOSED_TASK_STATUSES = frozenset({"completed", "cancelled"})
_REVIEW_TASK_STATUSES = frozenset({"running", "pending", "failed"})


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


def list_prunable_task_branches(
    repo_path: Path,
    *,
    branches: list[BranchInfo] | None = None,
    base_branch: str | None = None,
) -> list[str]:
    """Return orphan task branches that are already merged into the base branch."""
    branches = branches or get_all_branches(repo_path)
    orphan_branches = [b for b in branches if b.task_id and not b.has_worktree]
    merged_branches = _get_merged_branches(repo_path, base_branch or _detect_base_branch(repo_path))
    return [b.name for b in orphan_branches if b.name in merged_branches]


def prune_prunable_task_branches(repo_path: Path) -> list[str]:
    """Delete merged orphan task branches and return the ones removed."""
    removed: list[str] = []
    for branch_name in list_prunable_task_branches(repo_path):
        result = run_git(["branch", "-d", branch_name], repo_path)
        if result.returncode == 0:
            removed.append(branch_name)
    return removed


def list_equivalent_orphan_task_branches(
    repo_path: Path,
    *,
    branches: list[BranchInfo] | None = None,
    base_branch: str | None = None,
) -> list[str]:
    """Return orphan task branches whose tree matches the base branch exactly."""
    base_branch = base_branch or _detect_base_branch(repo_path)
    branches = branches or get_all_branches(repo_path)
    return [
        b.name
        for b in branches
        if b.task_id and not b.has_worktree and not _branch_diff_paths(repo_path, b.name, base_branch)
    ]


def _prune_branch_list(repo_path: Path, branch_names: list[str], base_branch: str) -> list[str]:
    """Force-delete a list of branches, checking out base first if any is current."""
    removed: list[str] = []
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    current_branch = result.stdout.strip() if result.returncode == 0 else ""
    for branch_name in branch_names:
        if current_branch == branch_name:
            if run_git(["checkout", base_branch], repo_path).returncode != 0:
                continue
            current_branch = base_branch
        if run_git(["branch", "-D", branch_name], repo_path).returncode == 0:
            removed.append(branch_name)
    return removed


def prune_equivalent_orphan_task_branches(repo_path: Path) -> list[str]:
    """Delete orphan task branches whose tree matches base exactly."""
    base_branch = _detect_base_branch(repo_path)
    return _prune_branch_list(repo_path, list_equivalent_orphan_task_branches(repo_path), base_branch)


def list_closed_orphan_task_branches(repo_path: Path) -> list[str]:
    """Return orphan task branches whose linked task is already terminal."""
    from app.storage import tasks as task_store

    return [
        branch.name
        for branch in get_all_branches(repo_path)
        if branch.task_id
        and not branch.has_worktree
        and (task := task_store.get_task(branch.task_id)) is not None
        and task.get("status") in _CLOSED_TASK_STATUSES
    ]


def prune_closed_orphan_task_branches(repo_path: Path) -> list[str]:
    """Delete orphan task branches when the linked task is already closed."""
    base_branch = _detect_base_branch(repo_path)
    return _prune_branch_list(repo_path, list_closed_orphan_task_branches(repo_path), base_branch)


def assess_orphan_task_branches(
    repo_path: Path,
    *,
    branches: list[BranchInfo] | None = None,
    base_branch: str | None = None,
) -> list[OrphanBranchAssessment]:
    """Classify orphan task branches that still need resolution."""
    from app.storage import tasks as task_store

    base_branch = base_branch or _detect_base_branch(repo_path)
    branches = branches or get_all_branches(repo_path)
    merged_branch_names = _get_merged_branches(repo_path, base_branch)
    equivalent_branch_names = set(
        list_equivalent_orphan_task_branches(
            repo_path,
            branches=branches,
            base_branch=base_branch,
        )
    )

    assessments: list[OrphanBranchAssessment] = []
    for branch in branches:
        if not branch.task_id or branch.has_worktree:
            continue
        if branch.name in merged_branch_names or branch.name in equivalent_branch_names:
            continue

        diff_paths = _branch_diff_paths(repo_path, branch.name, base_branch)
        task = task_store.get_task(branch.task_id)
        task_status = task.get("status") if task else None
        resolution = "salvage" if task is None or task_status in _CLOSED_TASK_STATUSES else "review"
        has_node_modules = any(
            p == "node_modules" or p.startswith("node_modules/") for p in diff_paths
        )
        assessments.append(OrphanBranchAssessment(
            branch_name=branch.name,
            task_id=branch.task_id,
            resolution=resolution,
            task_status=task_status,
            commits_ahead=_branch_commits_ahead(repo_path, branch.name, base_branch),
            files_changed=len(diff_paths),
            has_node_modules_artifact=has_node_modules,
        ))
    return assessments


def build_repo_workspace_summary(
    repo_path: Path,
    project_id: str | None = None,
    *,
    branches: list[BranchInfo] | None = None,
    active_worktrees: list | None = None,
) -> RepoWorkspaceSummary:
    """Build per-repository branch/worktree cleanup counters."""
    from ..api.models.git_models import RepoWorkspaceSummary
    from ._git_core import has_uncommitted_changes

    resolved_project_id = _resolve_project_id(repo_path, project_id)
    active_worktrees = (
        active_worktrees
        if active_worktrees is not None
        else (_get_active_worktrees(resolved_project_id) if resolved_project_id else [])
    )
    branches = branches or get_all_branches(
        repo_path,
        resolved_project_id,
        active_worktrees=active_worktrees,
    )
    base_branch = _detect_base_branch(repo_path)
    dirty_main_repo = has_uncommitted_changes(repo_path)
    dirty_worktrees = sum(1 for wt in active_worktrees if has_uncommitted_changes(wt.path))
    task_branches = [b for b in branches if b.task_id]
    orphan_branches = [b for b in task_branches if not b.has_worktree]
    prunable_names = set(
        list_prunable_task_branches(
            repo_path,
            branches=branches,
            base_branch=base_branch,
        )
    )
    prunable_branches = [b for b in orphan_branches if b.name in prunable_names]
    orphan_assessments = assess_orphan_task_branches(
        repo_path,
        branches=branches,
        base_branch=base_branch,
    )

    return RepoWorkspaceSummary(
        active_worktrees=len(active_worktrees),
        dirty_worktrees=dirty_worktrees,
        dirty_main_repo=dirty_main_repo,
        branches_with_worktrees=sum(1 for b in task_branches if b.has_worktree),
        task_branches=len(task_branches),
        orphan_branches=len(orphan_branches),
        prunable_branches=len(prunable_branches),
        needs_cleanup=bool(dirty_main_repo or dirty_worktrees or orphan_branches or prunable_branches),
        worktree_task_ids=[wt.task_id for wt in active_worktrees[:2]],
        orphan_branch_names=[b.name for b in orphan_branches[:5]],
        prunable_branch_names=[b.name for b in prunable_branches[:5]],
        salvage_task_ids=[a.task_id for a in orphan_assessments if a.resolution == "salvage"][:5],
        review_orphan_task_ids=[a.task_id for a in orphan_assessments if a.resolution == "review"][:5],
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
