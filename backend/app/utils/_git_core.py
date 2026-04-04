"""Core git primitives: run_git, repo status, sync operations."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api.models.git_models import RepoStatus, SyncResult

from ..logging_config import get_logger

# Re-export repo-source helpers so existing imports and mocks on this module work.
from ._git_repo_sources import (  # noqa: F401
    FALLBACK_FILE,
    WORKTREES_BASE_DIR,
    _collect_db_extra_repos,
    _collect_db_repos,
    _is_shadowed_project_repo,
    _load_repo_paths_from_file,
    _merge_managed_repos,
    _normalize_repo_path,
    _query_db_extra_repos,
    _query_db_project_roots,
    _query_db_root_paths,
    _registered_project_roots,
    _resolve_project_id_from_sources,
    _translate_path,
)

logger = get_logger(__name__)


def is_valid_git_repo(path: Path) -> bool:
    """Return True if path exists and has a .git directory."""
    return path.exists() and (path / ".git").exists()


CONFIG_REPOS: list[Path] = _load_repo_paths_from_file(FALLBACK_FILE)

# Git subcommands and arguments
_GIT_REV_PARSE_HEAD = ["rev-parse", "--abbrev-ref", "HEAD"]
_GIT_STATUS_PORCELAIN = ["status", "--porcelain"]
_GIT_FETCH_ALL = ["fetch", "--all", "--prune"]
_GIT_PULL_FF = ["pull", "--ff-only"]
_GIT_PUSH = ["push"]
_GIT_REV_LIST_LR_COUNT = ["rev-list", "--left-right", "--count"]

# Status and state values
_STATUS_FAILED = "failed"
_STATUS_UPDATED = "updated"
_STATUS_UP_TO_DATE = "up_to_date"
_STATUS_SKIPPED = "skipped"
_STATUS_UNKNOWN = "unknown"

_STATE_DIRTY = "dirty"
_STATE_BEHIND = "behind"
_STATE_AHEAD = "ahead"
_STATE_CLEAN = "clean"

# Output substrings
_GIT_ALREADY_UP_TO_DATE = "Already up to date"

# Error / reason messages
_ERR_NO_REPO_STATUS = "Could not get repository status"
_REASON_UNCOMMITTED = "uncommitted changes"


def _resolve_project_id(repo_path: Path, project_id: str | None = None) -> str | None:
    """Resolve a project id using this module's repo-source collaborators.

    Keeping this wrapper in `_git_core` preserves the long-standing patch surface
    for tests and callers that mock `_git_core` helpers directly.
    """
    return _resolve_project_id_from_sources(
        repo_path,
        _query_db_project_roots(),
        project_id=project_id,
        translate_path=_translate_path,
    )


def get_managed_repos() -> list[Path]:
    """Get managed repos using this module's locally patchable helper surface."""
    return _merge_managed_repos(
        _collect_db_repos(),
        _collect_db_extra_repos(),
        _registered_project_roots(),
        _load_repo_paths_from_file(FALLBACK_FILE),
        validate_repo=is_valid_git_repo,
        is_shadowed_project_repo=_is_shadowed_project_repo,
    )


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def has_uncommitted_changes(worktree_path: Path) -> bool:
    """Check if worktree has uncommitted changes."""
    result = run_git(["status", "--porcelain"], worktree_path)
    return bool(result.stdout.strip())


def _make_failed_sync(repo_path: Path, branch: str = _STATUS_UNKNOWN, error: str = "") -> SyncResult:
    """Build a failed SyncResult."""
    from ..api.models.git_models import SyncResult

    return SyncResult(
        path=str(repo_path),
        name=repo_path.name,
        branch=branch,
        status=_STATUS_FAILED,
        error=error or _ERR_NO_REPO_STATUS,
    )


def _get_current_branch(repo_path: Path) -> str | None:
    """Return the current branch name, or None if it cannot be determined."""
    result = run_git(_GIT_REV_PARSE_HEAD, repo_path)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _count_uncommitted(repo_path: Path) -> int:
    """Return the number of uncommitted changes in the working tree."""
    sr = run_git(_GIT_STATUS_PORCELAIN, repo_path)
    if sr.returncode != 0:
        return 0
    return len([ln for ln in sr.stdout.strip().split("\n") if ln])


def _get_ahead_behind(repo_path: Path, branch: str) -> tuple[int, int]:
    """Return (ahead, behind) commit counts relative to origin/<branch>."""
    args = [*_GIT_REV_LIST_LR_COUNT, f"{branch}...origin/{branch}"]
    rr = run_git(args, repo_path)
    if rr.returncode != 0:
        return 0, 0
    parts = rr.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0
    return int(parts[0]), int(parts[1])


def _classify_state(uncommitted: int, behind: int, ahead: int) -> str:
    """Return a state label based on repo counters."""
    if uncommitted > 0:
        return _STATE_DIRTY
    if behind > 0:
        return _STATE_BEHIND
    if ahead > 0:
        return _STATE_AHEAD
    return _STATE_CLEAN


def get_repo_status(
    repo_path: Path,
    project_id: str | None = None,
    *,
    active_worktrees_by_project: dict[str, list] | None = None,
) -> RepoStatus | None:
    """Get status information for a git repository."""
    from ..api.models.git_models import RepoStatus
    from ._git_branches import build_repo_workspace_summary, get_all_branches

    if not is_valid_git_repo(repo_path):
        return None

    branch = _get_current_branch(repo_path)
    if branch is None:
        return None

    uncommitted = _count_uncommitted(repo_path)
    ahead, behind = _get_ahead_behind(repo_path, branch)
    state = _classify_state(uncommitted, behind, ahead)
    resolved_project_id = _resolve_project_id(repo_path, project_id)
    active_worktrees = (
        active_worktrees_by_project.get(resolved_project_id, [])
        if active_worktrees_by_project is not None and resolved_project_id
        else None
    )
    branches = get_all_branches(
        repo_path,
        resolved_project_id,
        active_worktrees=active_worktrees,
    )

    return RepoStatus(
        path=str(repo_path),
        name=repo_path.name,
        project_id=resolved_project_id,
        branch=branch,
        uncommitted=uncommitted,
        ahead=ahead,
        behind=behind,
        state=state,
        workspace_summary=build_repo_workspace_summary(
            repo_path,
            resolved_project_id,
            branches=branches,
            active_worktrees=active_worktrees,
        ),
    )


def sync_repository(repo_path: Path) -> SyncResult:
    """Sync a repository by pulling from remote."""
    return pull_repository(repo_path)


def fetch_repository(repo_path: Path) -> SyncResult:
    """Fetch changes from remote without merging."""
    from ..api.models.git_models import SyncResult

    result = SyncResult(path=str(repo_path), name=repo_path.name, branch=_STATUS_UNKNOWN, status=_STATUS_UNKNOWN)
    repo_status = get_repo_status(repo_path)
    if repo_status:
        result.branch = repo_status.branch
    gr = run_git(_GIT_FETCH_ALL, repo_path)
    result.status = _STATUS_UPDATED if gr.returncode == 0 else _STATUS_FAILED
    if gr.returncode != 0:
        result.error = gr.stderr.strip()
    return result


def pull_repository(repo_path: Path) -> SyncResult:
    """Pull changes from remote (fast-forward only)."""
    from ..api.models.git_models import SyncResult

    repo_status = get_repo_status(repo_path)
    if not repo_status:
        return _make_failed_sync(repo_path)
    if repo_status.uncommitted > 0:
        return SyncResult(
            path=str(repo_path),
            name=repo_path.name,
            branch=repo_status.branch,
            status=_STATUS_SKIPPED,
            reason=_REASON_UNCOMMITTED,
        )
    gr = run_git(_GIT_PULL_FF, repo_path)
    if gr.returncode != 0:
        return _make_failed_sync(repo_path, repo_status.branch, gr.stderr.strip())
    status = _STATUS_UP_TO_DATE if _GIT_ALREADY_UP_TO_DATE in gr.stdout else _STATUS_UPDATED
    return SyncResult(path=str(repo_path), name=repo_path.name, branch=repo_status.branch, status=status)


def push_repository(repo_path: Path) -> SyncResult:
    """Push changes to remote."""
    from ..api.models.git_models import SyncResult

    repo_status = get_repo_status(repo_path)
    if not repo_status:
        return _make_failed_sync(repo_path)
    gr = run_git(_GIT_PUSH, repo_path)
    if gr.returncode != 0:
        return _make_failed_sync(repo_path, repo_status.branch, gr.stderr.strip())
    return SyncResult(path=str(repo_path), name=repo_path.name, branch=repo_status.branch, status=_STATUS_UPDATED)
