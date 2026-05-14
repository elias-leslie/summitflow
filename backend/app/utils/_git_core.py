"""Core git primitives: run_git, repo status, sync operations."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api.models.git_models import RepoStatus, SyncResult

from ..logging_config import get_logger
from . import safe_subprocess

# Re-export repo-source helpers so existing imports and mocks on this module work.
from ._git_repo_sources import (  # noqa: F401
    FALLBACK_FILE,
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
_GIT_REMOTE_DEFAULT_BRANCH = ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]

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
    return safe_subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def has_uncommitted_changes(repo_path: Path) -> bool:
    """Check if a repository checkout has uncommitted changes."""
    result = run_git(["status", "--porcelain"], repo_path)
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


def _get_jj_status(repo_path: Path):
    """Return jj status for colocated repos, falling back to Git on jj errors."""
    try:
        from cli.lib.jj import JJError, is_colocated, status_summary
    except ImportError:
        return None
    if not is_colocated(repo_path):
        return None
    try:
        return status_summary(repo_path)
    except JJError:
        return None


def _git_remote_default_branch(repo_path: Path) -> str:
    result = run_git(_GIT_REMOTE_DEFAULT_BRANCH, repo_path)
    if result.returncode != 0:
        return ""
    branch = result.stdout.strip()
    if branch.startswith("origin/"):
        return branch.removeprefix("origin/")
    return branch


def _make_skipped_sync(repo_path: Path, branch: str) -> SyncResult:
    from ..api.models.git_models import SyncResult

    return SyncResult(
        path=str(repo_path),
        name=repo_path.name,
        branch=branch,
        status=_STATUS_SKIPPED,
        reason=_REASON_UNCOMMITTED,
    )


def _resolve_pull_branch(repo_path: Path, branch: str) -> str:
    if branch != "HEAD":
        return branch
    return _git_remote_default_branch(repo_path)


def _can_rebase_empty_jj_working_copy(status_result, current, parent, target) -> bool:
    return (
        status_result.returncode == 0
        and current is not None
        and parent is not None
        and target is not None
        and "The working copy has no changes." in status_result.stdout
        and current.empty
        and not current.description.strip()
        and not current.conflict
        and target.commit_id not in {current.commit_id, parent.commit_id}
    )


def _maybe_rebase_jj_working_copy(repo_path: Path, branch: str, run_jj, current_revision_info, revision_info, jj_error) -> bool | SyncResult:
    status_result = run_jj(repo_path, ["status"])
    try:
        current = current_revision_info(repo_path)
        parent = revision_info(repo_path, "@-")
        target = revision_info(repo_path, branch)
    except jj_error:
        current = parent = target = None
    if not _can_rebase_empty_jj_working_copy(status_result, current, parent, target):
        return False
    rebase = run_jj(repo_path, ["rebase", "-r", "@", "-d", branch])
    if rebase.returncode != 0:
        return _make_failed_sync(repo_path, branch, (rebase.stderr or rebase.stdout).strip())
    return True


def _pull_jj_repository(repo_path: Path, repo_status: RepoStatus) -> SyncResult | None:
    """Fetch a colocated jj repo and keep a clean empty workspace on its bookmark."""
    from ..api.models.git_models import SyncResult

    try:
        from cli.lib.jj import JJError, current_revision_info, is_colocated, revision_info, run_jj
    except ImportError:
        return None
    if not is_colocated(repo_path):
        return None
    if repo_status.uncommitted > 0:
        return _make_skipped_sync(repo_path, repo_status.branch)

    fetch = run_jj(repo_path, ["git", "fetch", "--remote", "origin"])
    if fetch.returncode != 0:
        return _make_failed_sync(repo_path, repo_status.branch, (fetch.stderr or fetch.stdout).strip())

    branch = _resolve_pull_branch(repo_path, repo_status.branch)
    rebased = False
    if branch:
        rebase_result = _maybe_rebase_jj_working_copy(
            repo_path,
            branch,
            run_jj,
            current_revision_info,
            revision_info,
            JJError,
        )
        if isinstance(rebase_result, SyncResult):
            return rebase_result
        rebased = rebase_result

    detail = "\n".join(part for part in (fetch.stdout, fetch.stderr) if part)
    status_name = _STATUS_UP_TO_DATE if not rebased and "Nothing changed" in detail else _STATUS_UPDATED
    return SyncResult(
        path=str(repo_path),
        name=repo_path.name,
        branch=branch or repo_status.branch,
        status=status_name,
    )


def _classify_state(uncommitted: int, behind: int, ahead: int) -> str:
    """Return a state label based on repo counters."""
    if uncommitted > 0:
        return _STATE_DIRTY
    if behind > 0:
        return _STATE_BEHIND
    if ahead > 0:
        return _STATE_AHEAD
    return _STATE_CLEAN


def _repo_branch_and_uncommitted(repo_path: Path, jj_status) -> tuple[str | None, int]:
    if jj_status is not None:
        uncommitted = 0 if jj_status.state in {_STATE_CLEAN, "unpublished"} else 1
        return jj_status.branch, uncommitted
    branch = _get_current_branch(repo_path)
    if branch is None:
        return None, 0
    return branch, _count_uncommitted(repo_path)



def _active_checkpoints_for_project(
    resolved_project_id: str | None,
    active_checkpoints_by_project: dict[str, list] | None,
) -> list | None:
    if active_checkpoints_by_project is None or not resolved_project_id:
        return None
    return active_checkpoints_by_project.get(resolved_project_id, [])



def get_repo_status(
    repo_path: Path,
    project_id: str | None = None,
    *,
    active_checkpoints_by_project: dict[str, list] | None = None,
) -> RepoStatus | None:
    """Get status information for a git repository."""
    from ..api.models.git_models import RepoStatus
    from ._git_branches import build_repo_workspace_summary, get_all_branches

    if not is_valid_git_repo(repo_path):
        return None

    jj_status = _get_jj_status(repo_path)
    branch, uncommitted = _repo_branch_and_uncommitted(repo_path, jj_status)
    if branch is None:
        return None
    ahead, behind = _get_ahead_behind(repo_path, branch)
    if jj_status is not None:
        ahead = max(ahead, jj_status.unpublished)
    state = _classify_state(uncommitted, behind, ahead)
    resolved_project_id = _resolve_project_id(repo_path, project_id)
    active_checkpoints = _active_checkpoints_for_project(
        resolved_project_id,
        active_checkpoints_by_project,
    )
    branches = get_all_branches(
        repo_path,
        resolved_project_id,
        active_checkpoints=active_checkpoints,
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
            active_checkpoints=active_checkpoints,
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
    jj_result = _pull_jj_repository(repo_path, repo_status)
    if jj_result is not None:
        return jj_result
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
