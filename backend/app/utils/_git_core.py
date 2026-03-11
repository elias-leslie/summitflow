"""Core git primitives: run_git, repo status, sync operations."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api.models.git_models import RepoStatus, SyncResult

from ..logging_config import get_logger

logger = get_logger(__name__)

CONFIG_REPOS = [Path.home() / ".claude"]
WORKTREES_BASE_DIR = Path.home() / ".summitflow" / "worktrees"

# Git subcommands and arguments
_GIT_REV_PARSE_HEAD = ["rev-parse", "--abbrev-ref", "HEAD"]
_GIT_STATUS_PORCELAIN = ["status", "--porcelain"]
_GIT_FETCH_ALL = ["fetch", "--all", "--prune"]
_GIT_PULL_FF = ["pull", "--ff-only"]
_GIT_PUSH = ["push"]

# SQL
_SQL_SELECT_ROOT_PATHS = "SELECT root_path FROM projects WHERE root_path IS NOT NULL"

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

# Rev-list format for ahead/behind tracking
_GIT_REV_LIST_LR_COUNT = ["rev-list", "--left-right", "--count"]


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


def is_valid_git_repo(path: Path) -> bool:
    """Return True if path exists and has a .git directory."""
    return path.exists() and (path / ".git").exists()


def _query_db_root_paths() -> list[str]:
    """Return raw root_path values from the projects table, or [] on error."""
    from ..storage.connection import get_connection

    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(_SQL_SELECT_ROOT_PATHS)
            return [row[0] for row in cur.fetchall()]
    except Exception:
        logger.debug("Failed to query managed repos from database", exc_info=True)
        return []


def _collect_db_repos() -> list[Path]:
    """Return valid git repo paths from the database."""
    repos: list[Path] = []
    for raw in _query_db_root_paths():
        path = Path(raw)
        if is_valid_git_repo(path):
            repos.append(path)
    return repos


def get_managed_repos() -> list[Path]:
    """Get list of managed repos from database + config repos."""
    repos = _collect_db_repos()
    for config_repo in CONFIG_REPOS:
        if is_valid_git_repo(config_repo) and config_repo not in repos:
            repos.append(config_repo)
    return repos


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


def get_repo_status(repo_path: Path) -> RepoStatus | None:
    """Get status information for a git repository."""
    from ..api.models.git_models import RepoStatus
    from ._git_branches import build_repo_workspace_summary

    if not is_valid_git_repo(repo_path):
        return None

    branch = _get_current_branch(repo_path)
    if branch is None:
        return None

    uncommitted = _count_uncommitted(repo_path)
    ahead, behind = _get_ahead_behind(repo_path, branch)
    state = _classify_state(uncommitted, behind, ahead)

    return RepoStatus(
        path=str(repo_path),
        name=repo_path.name,
        branch=branch,
        uncommitted=uncommitted,
        ahead=ahead,
        behind=behind,
        state=state,
        workspace_summary=build_repo_workspace_summary(repo_path),
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
