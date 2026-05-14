"""Cleanup and orphan-branch helpers built on top of branch queries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import _git_core as git_core
from . import _git_safe_task_refs as safe_task_refs

if TYPE_CHECKING:
    from ..api.models.git_models import BranchInfo, OrphanBranchSummary, RepoWorkspaceSummary

_CLOSED_TASK_STATUSES = frozenset({"completed", "cancelled"})
SafeTaskRef = safe_task_refs.SafeTaskRef
list_safe_task_refs = safe_task_refs.list_safe_task_refs
prune_safe_task_refs = safe_task_refs.prune_safe_task_refs


@dataclass(frozen=True)
class OrphanBranchAssessment:
    """Classification result for an orphan task branch."""

    branch_name: str
    task_id: str
    resolution: str
    task_status: str | None
    task_token: str
    commits_ahead: int
    files_changed: int
    has_node_modules_artifact: bool
    commits_behind: int = 0


def _git_branches_module():
    """Import branch-query helpers lazily to avoid module-level cycles."""
    from . import _git_branches

    return _git_branches


def _orphan_task_branches(branches: list[BranchInfo]) -> list[BranchInfo]:
    """Return task branches that no longer have active checkpoint metadata."""
    return [branch for branch in branches if branch.task_id and not branch.has_checkpoint]


def _has_node_modules_artifact(diff_paths: list[str]) -> bool:
    """Return True when branch-only changes include node_modules residue."""
    return any(path == "node_modules" or path.startswith("node_modules/") for path in diff_paths)


def _load_task_status(task_id: str) -> tuple[str | None, str]:
    """Return persisted task status plus assessment token for an orphan branch."""
    from app.storage import tasks as task_store

    try:
        task = task_store.get_task(task_id)
    except Exception:
        return None, "task:unreadable"

    if task is None:
        return None, "task:missing"

    if not hasattr(task, "get"):
        return None, "task:unreadable"

    status = task.get("status")
    if status is None:
        return None, "task:unreadable"
    if not isinstance(status, str):
        return None, "task:unreadable"
    return status, f"task:{status}"


def _resolution_for_task_status(task_token: str) -> str:
    """Classify whether an orphan branch needs salvage or active review."""
    return "salvage" if task_token == "task:missing" else "review"


def _build_orphan_branch_assessment(
    repo_path: Path,
    branch: BranchInfo,
    base_branch: str,
) -> OrphanBranchAssessment:
    """Build a single orphan-branch assessment from current diff state."""
    git_branches = _git_branches_module()
    task_id = branch.task_id
    if task_id is None:
        raise ValueError(f"Expected orphan task branch with task_id: {branch.name}")

    diff_paths = git_branches._branch_ahead_diff_paths(repo_path, branch.name, base_branch)
    task_status, task_token = _load_task_status(task_id)
    return OrphanBranchAssessment(
        branch_name=branch.name,
        task_id=task_id,
        resolution=_resolution_for_task_status(task_token),
        task_status=task_status,
        task_token=task_token,
        commits_ahead=git_branches._branch_commits_ahead(repo_path, branch.name, base_branch),
        files_changed=len(diff_paths),
        has_node_modules_artifact=_has_node_modules_artifact(diff_paths),
        commits_behind=git_branches._branch_commits_behind(repo_path, branch.name, base_branch),
    )


def _resolve_workspace_inventory(
    repo_path: Path,
    project_id: str | None,
    *,
    branches: list[BranchInfo] | None,
    active_checkpoints: list | None,
) -> tuple[str | None, list, list[BranchInfo], str]:
    """Resolve checkpoints, branches, and base branch for cleanup calculations."""
    git_branches = _git_branches_module()
    resolved_project_id = git_branches._resolve_project_id(repo_path, project_id)
    checkpoints = (
        active_checkpoints
        if active_checkpoints is not None
        else (git_branches._get_active_checkpoints(resolved_project_id) if resolved_project_id else [])
    )
    resolved_branches = branches or git_branches.get_all_branches(
        repo_path,
        resolved_project_id,
        active_checkpoints=checkpoints,
    )
    return resolved_project_id, checkpoints, resolved_branches, git_branches._detect_base_branch(repo_path)


def _lane_active_checkpoints(checkpoints: list) -> list:
    """Return checkpoint metadata for tasks that still occupy an active work lane."""
    return [
        checkpoint
        for checkpoint in checkpoints
        if _load_task_status(str(checkpoint.task_id))[0] != "paused"
    ]


def _prune_branch_list(repo_path: Path, branch_names: list[str], base_branch: str) -> list[str]:
    """Force-delete a list of branches, checking out base first if any is current."""
    git_branches = _git_branches_module()
    removed: list[str] = []
    current_branch = _current_branch_name(repo_path)
    for branch_name in branch_names:
        next_branch = _checkout_base_if_current(
            repo_path,
            branch_name,
            base_branch,
            current_branch,
        )
        if next_branch is None:
            continue
        current_branch = next_branch
        if git_branches.run_git(["branch", "-D", branch_name], repo_path).returncode == 0:
            removed.append(branch_name)
    return removed


def _current_branch_name(repo_path: Path) -> str:
    """Return current branch name when available."""
    git_branches = _git_branches_module()
    result = git_branches.run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    return result.stdout.strip() if result.returncode == 0 else ""


def _checkout_base_if_current(
    repo_path: Path,
    branch_name: str,
    base_branch: str,
    current_branch: str,
) -> str | None:
    """Switch to base branch before pruning current branch."""
    if current_branch != branch_name:
        return current_branch
    git_branches = _git_branches_module()
    if git_branches.run_git(["checkout", base_branch], repo_path).returncode != 0:
        return None
    return base_branch



def _branch_cleanup_stats(repo_path: Path, branch_name: str, base_branch: str) -> tuple[int, int, int]:
    """Return ahead count, behind count, and changed file count for a branch."""
    git_branches = _git_branches_module()
    return (
        git_branches._branch_commits_ahead(repo_path, branch_name, base_branch),
        git_branches._branch_commits_behind(repo_path, branch_name, base_branch),
        len(git_branches._branch_ahead_diff_paths(repo_path, branch_name, base_branch)),
    )



def _apply_branch_cleanup_stats(
    branch: BranchInfo,
    *,
    cleanup_resolution: str,
    commits_ahead: int,
    commits_behind: int,
    files_changed: int,
) -> None:
    """Apply shared cleanup fields to a branch row."""
    branch.cleanup_resolution = cleanup_resolution
    branch.commits_ahead = commits_ahead
    branch.commits_behind = commits_behind
    branch.files_changed = files_changed



def _apply_assessment(branch: BranchInfo, assessment: OrphanBranchAssessment) -> None:
    """Apply assessment fields to a branch row."""
    branch.cleanup_resolution = assessment.resolution
    branch.task_status = assessment.task_status
    branch.commits_ahead = assessment.commits_ahead
    branch.commits_behind = assessment.commits_behind
    branch.files_changed = assessment.files_changed
    branch.has_node_modules_artifact = assessment.has_node_modules_artifact



def _current_checkpoint_task_id(branches: list[BranchInfo]) -> str | None:
    """Return current checkpoint task id when present."""
    return next(
        (
            branch.task_id
            for branch in branches
            if branch.is_current and branch.task_id and branch.has_checkpoint
        ),
        None,
    )



def _dirty_workspace_state(repo_path: Path, branches: list[BranchInfo]) -> tuple[bool, bool, bool]:
    """Return dirty main/checkpoint state plus cleanup need for dirty checkpoint."""
    dirty_repo = git_core.has_uncommitted_changes(repo_path)
    current_checkpoint_task_id = _current_checkpoint_task_id(branches)
    dirty_checkpoint = bool(dirty_repo and current_checkpoint_task_id)
    dirty_checkpoint_status = (
        _load_task_status(current_checkpoint_task_id)[0] if current_checkpoint_task_id else None
    )
    dirty_main_repo = bool(dirty_repo and not dirty_checkpoint)
    dirty_checkpoint_needs_cleanup = bool(
        dirty_checkpoint and dirty_checkpoint_status != "running"
    )
    return dirty_checkpoint, dirty_main_repo, dirty_checkpoint_needs_cleanup



def _orphan_cleanup_sets(
    repo_path: Path,
    branches: list[BranchInfo],
    base_branch: str,
) -> tuple[set[str], set[str], dict[str, OrphanBranchAssessment]]:
    """Return branch-name sets and assessments used by cleanup summaries."""
    git_branches = _git_branches_module()
    prunable_names = set(
        git_branches.list_prunable_task_branches(
            repo_path,
            branches=branches,
            base_branch=base_branch,
        )
    )
    equivalent_names = set(
        git_branches.list_equivalent_orphan_task_branches(
            repo_path,
            branches=branches,
            base_branch=base_branch,
        )
    )
    assessments = {
        assessment.branch_name: assessment
        for assessment in git_branches.assess_orphan_task_branches(
            repo_path,
            branches=branches,
            base_branch=base_branch,
        )
    }
    return prunable_names, equivalent_names, assessments



def _orphan_summary_inputs(
    repo_path: Path,
    branches: list[BranchInfo],
    base_branch: str,
) -> tuple[list[BranchInfo], list[BranchInfo], list[OrphanBranchAssessment]]:
    """Return orphan branches, prunable orphan branches, and assessments."""
    git_branches = _git_branches_module()
    orphan_branches = _orphan_task_branches(branches)
    equivalent_names = set(
        git_branches.list_equivalent_orphan_task_branches(
            repo_path,
            branches=branches,
            base_branch=base_branch,
        )
    )
    prunable_names = set(
        git_branches.list_prunable_task_branches(
            repo_path,
            branches=branches,
            base_branch=base_branch,
        )
    ) | equivalent_names
    prunable_branches = [branch for branch in orphan_branches if branch.name in prunable_names]
    orphan_assessments = git_branches.assess_orphan_task_branches(
        repo_path,
        branches=branches,
        base_branch=base_branch,
    )
    return orphan_branches, prunable_branches, orphan_assessments



def _repo_workspace_summary_payload(
    lane_checkpoints: list,
    task_branches: list[BranchInfo],
    orphan_branches: list[BranchInfo],
    prunable_branches: list[BranchInfo],
    orphan_assessments: list[OrphanBranchAssessment],
    dirty_checkpoint: bool,
    dirty_main_repo: bool,
    dirty_checkpoint_needs_cleanup: bool,
) -> dict:
    """Build RepoWorkspaceSummary kwargs."""
    return {
        "active_checkpoints": len(lane_checkpoints),
        "dirty_checkpoints": 1 if dirty_checkpoint else 0,
        "dirty_main_repo": dirty_main_repo,
        "branches_with_checkpoints": sum(1 for branch in task_branches if branch.has_checkpoint),
        "task_branches": len(task_branches),
        "orphan_branches": len(orphan_branches),
        "prunable_branches": len(prunable_branches),
        "needs_cleanup": bool(
            dirty_main_repo
            or dirty_checkpoint_needs_cleanup
            or orphan_branches
            or prunable_branches
        ),
        "checkpoint_task_ids": [checkpoint.task_id for checkpoint in lane_checkpoints],
        "orphan_branch_names": [branch.name for branch in orphan_branches[:5]],
        "prunable_branch_names": [branch.name for branch in prunable_branches[:5]],
        "salvage_task_ids": [
            assessment.task_id
            for assessment in orphan_assessments
            if assessment.resolution == "salvage"
        ][:5],
        "review_orphan_task_ids": [
            assessment.task_id
            for assessment in orphan_assessments
            if assessment.resolution == "review"
        ][:5],
        "orphan_details": [_orphan_summary(assessment) for assessment in orphan_assessments[:5]],
    }


def list_prunable_task_branches(
    repo_path: Path,
    *,
    branches: list[BranchInfo] | None = None,
    base_branch: str | None = None,
) -> list[str]:
    """Return orphan task branches that are already merged into the base branch."""
    git_branches = _git_branches_module()
    branches = branches or git_branches.get_all_branches(repo_path)
    merged_branches = git_branches._get_merged_branches(
        repo_path,
        base_branch or git_branches._detect_base_branch(repo_path),
    )
    return [branch.name for branch in _orphan_task_branches(branches) if branch.name in merged_branches]


def prune_prunable_task_branches(repo_path: Path) -> list[str]:
    """Delete merged orphan task branches and return the ones removed."""
    git_branches = _git_branches_module()
    removed: list[str] = []
    for branch_name in git_branches.list_prunable_task_branches(repo_path):
        if git_branches.run_git(["branch", "-d", branch_name], repo_path).returncode == 0:
            removed.append(branch_name)
    return removed


def list_equivalent_orphan_task_branches(
    repo_path: Path,
    *,
    branches: list[BranchInfo] | None = None,
    base_branch: str | None = None,
) -> list[str]:
    """Return orphan task branches whose payload is already present on base."""
    git_branches = _git_branches_module()
    base_branch = base_branch or git_branches._detect_base_branch(repo_path)
    branches = branches or git_branches.get_all_branches(repo_path)
    return [
        branch.name
        for branch in _orphan_task_branches(branches)
        if not git_branches._branch_diff_paths(repo_path, branch.name, base_branch)
        or not git_branches._branch_has_unapplied_patch(repo_path, branch.name, base_branch)
    ]


def prune_equivalent_orphan_task_branches(repo_path: Path) -> list[str]:
    """Delete orphan task branches whose tree matches base exactly."""
    git_branches = _git_branches_module()
    base_branch = git_branches._detect_base_branch(repo_path)
    return _prune_branch_list(repo_path, git_branches.list_equivalent_orphan_task_branches(repo_path), base_branch)


def list_closed_orphan_task_branches(repo_path: Path) -> list[str]:
    """Return orphan task branches whose linked task is already terminal."""
    git_branches = _git_branches_module()
    return [
        branch.name
        for branch in _orphan_task_branches(git_branches.get_all_branches(repo_path))
        if branch.task_id is not None
        and _load_task_status(branch.task_id)[0] in _CLOSED_TASK_STATUSES
    ]


def prune_closed_orphan_task_branches(repo_path: Path) -> list[str]:
    """Delete orphan task branches when the linked task is already closed."""
    git_branches = _git_branches_module()
    base_branch = git_branches._detect_base_branch(repo_path)
    return _prune_branch_list(repo_path, git_branches.list_closed_orphan_task_branches(repo_path), base_branch)


def assess_orphan_task_branches(
    repo_path: Path,
    *,
    branches: list[BranchInfo] | None = None,
    base_branch: str | None = None,
) -> list[OrphanBranchAssessment]:
    """Classify orphan task branches that still need resolution."""
    git_branches = _git_branches_module()
    base_branch = base_branch or git_branches._detect_base_branch(repo_path)
    branches = branches or git_branches.get_all_branches(repo_path)
    merged_branch_names = git_branches._get_merged_branches(repo_path, base_branch)
    equivalent_branch_names = set(
        git_branches.list_equivalent_orphan_task_branches(
            repo_path,
            branches=branches,
            base_branch=base_branch,
        )
    )
    return [
        _build_orphan_branch_assessment(repo_path, branch, base_branch)
        for branch in _orphan_task_branches(branches)
        if branch.name not in merged_branch_names and branch.name not in equivalent_branch_names
    ]


def _orphan_summary(assessment: OrphanBranchAssessment) -> OrphanBranchSummary:
    """Convert an internal assessment to the API cleanup summary shape."""
    from ..api.models.git_models import OrphanBranchSummary

    return OrphanBranchSummary(
        branch_name=assessment.branch_name,
        task_id=assessment.task_id,
        resolution=assessment.resolution,
        task_status=assessment.task_status,
        commits_ahead=assessment.commits_ahead,
        commits_behind=assessment.commits_behind,
        files_changed=assessment.files_changed,
        has_node_modules_artifact=assessment.has_node_modules_artifact,
    )


def enrich_branch_cleanup_details(
    repo_path: Path,
    branches: list[BranchInfo],
    *,
    base_branch: str | None = None,
) -> list[BranchInfo]:
    """Attach orphan cleanup action details to branch rows."""
    git_branches = _git_branches_module()
    base_branch = base_branch or git_branches._detect_base_branch(repo_path)
    prunable_names, equivalent_names, assessments = _orphan_cleanup_sets(
        repo_path,
        branches,
        base_branch,
    )

    for branch in branches:
        if not branch.task_id or branch.has_checkpoint:
            continue
        if branch.name in prunable_names:
            commits_ahead, commits_behind, files_changed = _branch_cleanup_stats(
                repo_path,
                branch.name,
                base_branch,
            )
            _apply_branch_cleanup_stats(
                branch,
                cleanup_resolution="prunable",
                commits_ahead=commits_ahead,
                commits_behind=commits_behind,
                files_changed=files_changed,
            )
            continue
        if branch.name in equivalent_names:
            commits_ahead, commits_behind, _files_changed = _branch_cleanup_stats(
                repo_path,
                branch.name,
                base_branch,
            )
            _apply_branch_cleanup_stats(
                branch,
                cleanup_resolution="equivalent",
                commits_ahead=commits_ahead,
                commits_behind=commits_behind,
                files_changed=0,
            )
            continue
        assessment = assessments.get(branch.name)
        if assessment:
            _apply_assessment(branch, assessment)
    return branches


def build_repo_workspace_summary(
    repo_path: Path,
    project_id: str | None = None,
    *,
    branches: list[BranchInfo] | None = None,
    active_checkpoints: list | None = None,
) -> RepoWorkspaceSummary:
    """Build per-repository branch/checkpoint cleanup counters."""
    from ..api.models.git_models import RepoWorkspaceSummary

    _resolved_project_id, checkpoints, branches, base_branch = _resolve_workspace_inventory(
        repo_path,
        project_id,
        branches=branches,
        active_checkpoints=active_checkpoints,
    )
    lane_checkpoints = _lane_active_checkpoints(checkpoints)
    dirty_checkpoint, dirty_main_repo, dirty_checkpoint_needs_cleanup = _dirty_workspace_state(
        repo_path,
        branches,
    )
    task_branches = [branch for branch in branches if branch.task_id]
    orphan_branches, prunable_branches, orphan_assessments = _orphan_summary_inputs(
        repo_path,
        branches,
        base_branch,
    )
    return RepoWorkspaceSummary(
        **_repo_workspace_summary_payload(
            lane_checkpoints,
            task_branches,
            orphan_branches,
            prunable_branches,
            orphan_assessments,
            dirty_checkpoint,
            dirty_main_repo,
            dirty_checkpoint_needs_cleanup,
        )
    )
