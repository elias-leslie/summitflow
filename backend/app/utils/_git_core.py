"""Core git primitives: run_git, repo status, sync operations."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api.models.git_models import RepoStatus, SyncResult

from ..logging_config import get_logger

logger = get_logger(__name__)

# Docker path translation: when running in Docker, host paths in the DB
# (e.g. /home/kasadis/summitflow) need to be mapped to the container mount
# (e.g. /host-home/summitflow). Set HOST_HOME_PATH + BACKUP_HOST_ROOT.
_HOST_HOME_PATH = os.environ.get("HOST_HOME_PATH", "")
_DOCKER_HOME_MOUNT = os.environ.get("BACKUP_HOST_ROOT", "")
FALLBACK_FILE = Path.home() / ".claude" / "config" / "managed-repos.txt"
CONFIG_REPOS: list[Path] = []
WORKTREES_BASE_DIR = Path.home() / ".summitflow" / "worktrees"

# Git subcommands and arguments
_GIT_REV_PARSE_HEAD = ["rev-parse", "--abbrev-ref", "HEAD"]
_GIT_STATUS_PORCELAIN = ["status", "--porcelain"]
_GIT_FETCH_ALL = ["fetch", "--all", "--prune"]
_GIT_PULL_FF = ["pull", "--ff-only"]
_GIT_PUSH = ["push"]

# SQL
_SQL_SELECT_ROOT_PATHS = "SELECT root_path FROM projects WHERE root_path IS NOT NULL"
_SQL_SELECT_PROJECT_ROOTS = "SELECT id, root_path FROM projects WHERE root_path IS NOT NULL"
_SQL_SELECT_EXTRA_REPOS = (
    "SELECT id, path FROM backup_sources "
    "WHERE path IS NOT NULL AND source_type IN ('config', 'workspace')"
)

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


def _load_repo_paths_from_file(path: Path) -> list[Path]:
    """Return valid git repo paths from a newline-delimited config file."""
    if not path.exists():
        return []

    repos: list[Path] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        candidate = Path(line).expanduser()
        if is_valid_git_repo(candidate):
            repos.append(candidate)
    return repos


CONFIG_REPOS = _load_repo_paths_from_file(FALLBACK_FILE)


def _query_db_root_paths() -> list[str]:
    """Return raw root_path values from the projects table, or [] on error."""
    from ..storage.connection import get_cursor

    try:
        with get_cursor() as cur:
            cur.execute(_SQL_SELECT_ROOT_PATHS)
            return [row[0] for row in cur.fetchall()]
    except Exception:
        logger.debug("Failed to query managed repos from database", exc_info=True)
        return []


def _query_db_project_roots() -> list[tuple[str, str]]:
    """Return project ids and raw root_path values from the projects table, or [] on error."""
    from ..storage.connection import get_cursor

    try:
        with get_cursor() as cur:
            cur.execute(_SQL_SELECT_PROJECT_ROOTS)
            return [(str(row[0]), str(row[1])) for row in cur.fetchall()]
    except Exception:
        logger.debug("Failed to query project repo mapping from database", exc_info=True)
        return []


def _query_db_extra_repos() -> list[tuple[str, str]]:
    """Return non-project managed repo ids and paths from backup_sources, or [] on error."""
    from ..storage.connection import get_cursor

    try:
        with get_cursor() as cur:
            cur.execute(_SQL_SELECT_EXTRA_REPOS)
            return [(str(row[0]), str(row[1])) for row in cur.fetchall()]
    except Exception:
        logger.debug("Failed to query config/workspace repos from backup_sources", exc_info=True)
        return []


def _translate_path(raw: str) -> Path:
    """Translate host path to Docker mount path if running in Docker."""
    if _HOST_HOME_PATH and _DOCKER_HOME_MOUNT and raw.startswith(_HOST_HOME_PATH):
        return Path(_DOCKER_HOME_MOUNT + raw[len(_HOST_HOME_PATH):])
    return Path(raw)


def _normalize_repo_path(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def _registered_project_roots() -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for db_project_id, raw_root in _query_db_project_roots():
        translated = _translate_path(raw_root)
        if not is_valid_git_repo(translated):
            continue
        roots[db_project_id] = _normalize_repo_path(translated)
    return roots


def _is_shadowed_project_repo(path: Path, project_roots: dict[str, Path]) -> bool:
    registered_root = project_roots.get(path.name)
    if registered_root is None:
        return False
    return _normalize_repo_path(path) != registered_root


def _collect_db_repos() -> list[Path]:
    """Return valid git repo paths from the database."""
    repos: list[Path] = []
    for raw in _query_db_root_paths():
        path = _translate_path(raw)
        if is_valid_git_repo(path):
            repos.append(path)
    return repos


def _collect_db_extra_repos() -> list[Path]:
    """Return valid config/workspace repo paths from backup_sources."""
    repos: list[Path] = []
    for _, raw in _query_db_extra_repos():
        path = _translate_path(raw)
        if is_valid_git_repo(path):
            repos.append(path)
    return repos


def _resolve_project_id(repo_path: Path, project_id: str | None = None) -> str | None:
    """Resolve the project id for a repo path when it is a registered project root.

    Only repositories from the projects table should receive a project_id.
    Config/workspace/backup repos are managed, but they are not project repos
    and should remain unscoped so the UI can treat them separately.
    """
    if project_id:
        return project_id

    try:
        candidate = repo_path.resolve()
    except OSError:
        candidate = repo_path

    for db_project_id, raw_root in _query_db_project_roots():
        translated_root = _translate_path(raw_root)
        try:
            root_path = translated_root.resolve()
        except OSError:
            root_path = translated_root
        if candidate == root_path:
            return db_project_id

    return None


def get_managed_repos() -> list[Path]:
    """Get list of managed repos from DB-backed sources plus local fallback repos."""
    repos = _collect_db_repos()
    project_roots = _registered_project_roots()
    for extra_repo in _collect_db_extra_repos():
        if _is_shadowed_project_repo(extra_repo, project_roots):
            continue
        if extra_repo not in repos:
            repos.append(extra_repo)
    for config_repo in _load_repo_paths_from_file(FALLBACK_FILE):
        if _is_shadowed_project_repo(config_repo, project_roots):
            continue
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


def get_repo_status(repo_path: Path, project_id: str | None = None) -> RepoStatus | None:
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
    resolved_project_id = _resolve_project_id(repo_path, project_id)

    return RepoStatus(
        path=str(repo_path),
        name=repo_path.name,
        project_id=resolved_project_id,
        branch=branch,
        uncommitted=uncommitted,
        ahead=ahead,
        behind=behind,
        state=state,
        workspace_summary=build_repo_workspace_summary(repo_path, resolved_project_id),
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
