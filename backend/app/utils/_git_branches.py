"""Git branch and checkpoint helpers."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api.models.git_models import BranchInfo, CheckpointInfo

from ._git_core import _resolve_project_id, run_git

_BASE_BRANCH_CANDIDATES = ["main", "master", "develop"]
_LEGACY_LANE_ADMIN_DIR = "wor" "ktrees"


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


def _get_active_checkpoints(project_id: str | None = None) -> list:
    """Load active checkpoints from the CLI source of truth."""
    from cli.lib.checkpoint import get_active_checkpoints

    return get_active_checkpoints(project_id)


def get_checkpoint_branches(
    project_id: str | None = None,
    *,
    active_checkpoints: list | None = None,
) -> dict[str, str]:
    """Get a mapping of active checkpoint branch names to task ids."""
    checkpoints = active_checkpoints if active_checkpoints is not None else _get_active_checkpoints(project_id)
    return {f"{checkpoint.task_id}/main": checkpoint.task_id for checkpoint in checkpoints}


def get_all_branches(
    repo_path: Path,
    project_id: str | None = None,
    *,
    active_checkpoints: list | None = None,
) -> list[BranchInfo]:
    """Get list of all local branches with checkpoint indicators."""
    from ..api.models.git_models import BranchInfo

    resolved_project_id = _resolve_project_id(repo_path, project_id)
    checkpoint_branches = get_checkpoint_branches(
        resolved_project_id,
        active_checkpoints=active_checkpoints,
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
            has_checkpoint=name in checkpoint_branches,
            repo_name=repo_path.name,
            project_id=resolved_project_id,
            task_id=extract_task_id_from_branch(name),
            last_commit_short=commit_short,
            last_commit_date=commit_date,
        ))

    branches.sort(key=lambda b: (not b.is_current, not b.has_checkpoint, b.name.lower()))
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


def prune_checkout_registrations(repo_path: Path) -> int:
    """Prune stale legacy lane git metadata registrations for a repository."""
    registrations_root = repo_path / ".git" / _LEGACY_LANE_ADMIN_DIR
    if not registrations_root.is_dir():
        return 0

    pruned = 0
    for registration in registrations_root.iterdir():
        gitdir_file = registration / "gitdir"
        if not gitdir_file.is_file():
            continue
        target = Path(gitdir_file.read_text(encoding="utf-8").strip())
        if not target.is_absolute():
            target = (registration / target).resolve()
        if target.exists():
            continue
        shutil.rmtree(registration, ignore_errors=False)
        pruned += 1
    return pruned


def get_checkpoint_info(task_id: str) -> CheckpointInfo | None:
    """Get information about an active checkpoint."""
    from cli.lib.checkpoint import get_active_checkpoints

    from ..api.models.git_models import CheckpointInfo

    for checkpoint in get_active_checkpoints():
        if checkpoint.task_id == task_id:
            return CheckpointInfo(
                task_id=checkpoint.task_id,
                branch=f"{checkpoint.task_id}/main",
                base_branch=checkpoint.base_branch,
                is_active=True,
                project_id=checkpoint.project_id,
            )
    return None


# Re-export cleanup helpers from a dedicated module to keep branch/query helpers compact.
from ._git_branch_cleanup import (  # noqa: E402
    OrphanBranchAssessment,
    assess_orphan_task_branches,
    build_repo_workspace_summary,
    enrich_branch_cleanup_details,
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
    "enrich_branch_cleanup_details",
    "extract_task_id_from_branch",
    "get_all_branches",
    "get_branch_commit_info",
    "get_checkpoint_branches",
    "get_checkpoint_info",
    "list_closed_orphan_task_branches",
    "list_equivalent_orphan_task_branches",
    "list_prunable_task_branches",
    "prune_checkout_registrations",
    "prune_closed_orphan_task_branches",
    "prune_equivalent_orphan_task_branches",
    "prune_prunable_task_branches",
]
