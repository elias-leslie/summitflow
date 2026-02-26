"""Core git primitives: run_git, repo status, sync operations."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from ..api.models.git_models import RepoStatus, SyncResult

logger = logging.getLogger(__name__)

CONFIG_REPOS = [Path.home() / ".claude"]
WORKTREES_BASE_DIR = Path.home() / ".summitflow" / "worktrees"


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


def get_managed_repos() -> list[Path]:
    """Get list of managed repos from database + config repos."""
    from ..storage.connection import get_connection

    repos: list[Path] = []
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT root_path FROM projects WHERE root_path IS NOT NULL")
            for row in cur.fetchall():
                path = Path(row[0])
                if is_valid_git_repo(path):
                    repos.append(path)
    except Exception:
        logger.debug("Failed to query managed repos from database", exc_info=True)

    for config_repo in CONFIG_REPOS:
        if is_valid_git_repo(config_repo) and config_repo not in repos:
            repos.append(config_repo)
    return repos


def _make_failed_sync(repo_path: Path, branch: str = "unknown", error: str = "") -> SyncResult:
    """Build a failed SyncResult."""
    return SyncResult(
        path=str(repo_path),
        name=repo_path.name,
        branch=branch,
        status="failed",
        error=error or "Could not get repository status",
    )


def get_repo_status(repo_path: Path) -> RepoStatus | None:
    """Get status information for a git repository."""
    if not is_valid_git_repo(repo_path):
        return None
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()

    uncommitted = 0
    sr = run_git(["status", "--porcelain"], repo_path)
    if sr.returncode == 0:
        uncommitted = len([ln for ln in sr.stdout.strip().split("\n") if ln])

    ahead = behind = 0
    rr = run_git(["rev-list", "--left-right", "--count", f"{branch}...origin/{branch}"], repo_path)
    if rr.returncode == 0:
        parts = rr.stdout.strip().split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])

    state = "dirty" if uncommitted > 0 else "behind" if behind > 0 else "ahead" if ahead > 0 else "clean"
    return RepoStatus(
        path=str(repo_path), name=repo_path.name, branch=branch,
        uncommitted=uncommitted, ahead=ahead, behind=behind, state=state,
    )


def sync_repository(repo_path: Path) -> SyncResult:
    """Sync a repository by pulling from remote."""
    return pull_repository(repo_path)


def fetch_repository(repo_path: Path) -> SyncResult:
    """Fetch changes from remote without merging."""
    result = SyncResult(path=str(repo_path), name=repo_path.name, branch="unknown", status="unknown")
    repo_status = get_repo_status(repo_path)
    if repo_status:
        result.branch = repo_status.branch
    gr = run_git(["fetch", "--all", "--prune"], repo_path)
    result.status = "updated" if gr.returncode == 0 else "failed"
    if gr.returncode != 0:
        result.error = gr.stderr.strip()
    return result


def pull_repository(repo_path: Path) -> SyncResult:
    """Pull changes from remote (fast-forward only)."""
    repo_status = get_repo_status(repo_path)
    if not repo_status:
        return _make_failed_sync(repo_path)
    if repo_status.uncommitted > 0:
        return SyncResult(
            path=str(repo_path), name=repo_path.name, branch=repo_status.branch,
            status="skipped", reason="uncommitted changes",
        )
    gr = run_git(["pull", "--ff-only"], repo_path)
    if gr.returncode != 0:
        return _make_failed_sync(repo_path, repo_status.branch, gr.stderr.strip())
    status = "up_to_date" if "Already up to date" in gr.stdout else "updated"
    return SyncResult(path=str(repo_path), name=repo_path.name, branch=repo_status.branch, status=status)


def push_repository(repo_path: Path) -> SyncResult:
    """Push changes to remote."""
    repo_status = get_repo_status(repo_path)
    if not repo_status:
        return _make_failed_sync(repo_path)
    gr = run_git(["push"], repo_path)
    if gr.returncode != 0:
        return _make_failed_sync(repo_path, repo_status.branch, gr.stderr.strip())
    return SyncResult(path=str(repo_path), name=repo_path.name, branch=repo_status.branch, status="updated")
