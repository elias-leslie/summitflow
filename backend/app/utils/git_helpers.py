"""Git utility functions."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from ..api.models.git_models import BranchInfo, RepoStatus, SyncResult, WorktreeInfo

logger = logging.getLogger(__name__)

# Config repos always included (not SummitFlow projects)
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


def get_managed_repos() -> list[Path]:
    """Get list of managed repos from database + config repos.

    Returns:
        List of Path objects for repos with valid .git directories.
    """
    from ..storage.connection import get_connection

    repos: list[Path] = []

    # Get project root paths from database
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT root_path FROM projects WHERE root_path IS NOT NULL")
            for row in cur.fetchall():
                path = Path(row[0])
                if path.exists() and (path / ".git").exists():
                    repos.append(path)
    except Exception:
        logger.debug("Failed to query managed repos from database", exc_info=True)
        pass

    # Always include config repos
    for config_repo in CONFIG_REPOS:
        if config_repo.exists() and (config_repo / ".git").exists() and config_repo not in repos:
            repos.append(config_repo)

    return repos


def get_repo_status(repo_path: Path) -> RepoStatus | None:
    """Get status information for a git repository."""
    if not repo_path.exists() or not (repo_path / ".git").exists():
        return None

    # Get current branch
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()

    # Get uncommitted changes count
    result = run_git(["status", "--porcelain"], repo_path)
    uncommitted = 0
    if result.returncode == 0:
        lines = [line for line in result.stdout.strip().split("\n") if line]
        uncommitted = len(lines)

    # Get ahead/behind counts
    ahead = 0
    behind = 0
    result = run_git(
        ["rev-list", "--left-right", "--count", f"{branch}...origin/{branch}"],
        repo_path,
    )
    if result.returncode == 0:
        parts = result.stdout.strip().split()
        if len(parts) == 2:
            ahead = int(parts[0])
            behind = int(parts[1])

    # Determine overall state
    if uncommitted > 0:
        state = "dirty"
    elif behind > 0:
        state = "behind"
    elif ahead > 0:
        state = "ahead"
    else:
        state = "clean"

    return RepoStatus(
        path=str(repo_path),
        name=repo_path.name,
        branch=branch,
        uncommitted=uncommitted,
        ahead=ahead,
        behind=behind,
        state=state,
    )


def sync_repository(repo_path: Path) -> SyncResult:
    """Sync a single repository by pulling from remote.

    Returns:
        SyncResult with status (up_to_date, updated, skipped, failed).
    """
    return pull_repository(repo_path)


def fetch_repository(repo_path: Path) -> SyncResult:
    """Fetch changes from remote without merging."""
    result = SyncResult(
        path=str(repo_path),
        name=repo_path.name,
        branch="unknown",
        status="unknown",
    )

    repo_status = get_repo_status(repo_path)
    if repo_status:
        result.branch = repo_status.branch

    # Run fetch
    git_result = run_git(["fetch", "--all", "--prune"], repo_path)

    if git_result.returncode == 0:
        result.status = "updated"
    else:
        result.status = "failed"
        result.error = git_result.stderr.strip()

    return result


def pull_repository(repo_path: Path) -> SyncResult:
    """Pull changes from remote (fast-forward only)."""
    repo_status = get_repo_status(repo_path)
    if not repo_status:
        return SyncResult(
            path=str(repo_path),
            name=repo_path.name,
            branch="unknown",
            status="failed",
            error="Could not get repository status",
        )

    result = SyncResult(
        path=str(repo_path),
        name=repo_path.name,
        branch=repo_status.branch,
        status="unknown",
    )

    # Skip dirty repos
    if repo_status.uncommitted > 0:
        result.status = "skipped"
        result.reason = "uncommitted changes"
        return result

    # Pull from remote
    git_result = run_git(["pull", "--ff-only"], repo_path)

    if git_result.returncode == 0:
        if "Already up to date" in git_result.stdout:
            result.status = "up_to_date"
        else:
            result.status = "updated"
    else:
        result.status = "failed"
        result.error = git_result.stderr.strip()

    return result


def push_repository(repo_path: Path) -> SyncResult:
    """Push changes to remote."""
    repo_status = get_repo_status(repo_path)
    if not repo_status:
        return SyncResult(
            path=str(repo_path),
            name=repo_path.name,
            branch="unknown",
            status="failed",
            error="Could not get repository status",
        )

    result = SyncResult(
        path=str(repo_path),
        name=repo_path.name,
        branch=repo_status.branch,
        status="unknown",
    )

    # Push to remote
    git_result = run_git(["push"], repo_path)

    if git_result.returncode == 0:
        result.status = "updated"
    else:
        result.status = "failed"
        result.error = git_result.stderr.strip()

    return result


def get_worktree_info(task_id: str) -> WorktreeInfo | None:
    """Get information about an existing worktree."""
    worktree_path = WORKTREES_BASE_DIR / task_id

    if not worktree_path.exists():
        return None

    # Verify it's a valid git worktree
    git_dir = worktree_path / ".git"
    if not git_dir.exists():
        return None

    # Get current branch
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], worktree_path)
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()

    # Determine base branch
    base_branch = "main"
    for candidate in ["main", "master", "develop"]:
        result = run_git(
            ["rev-parse", "--verify", f"origin/{candidate}"],
            worktree_path,
        )
        if result.returncode == 0:
            base_branch = candidate
            break

    return WorktreeInfo(
        task_id=task_id,
        path=str(worktree_path),
        branch=branch,
        base_branch=base_branch,
        is_active=True,
    )


def extract_task_id_from_branch(branch_name: str) -> str | None:
    """Extract task ID from branch name if it follows task-xxx/main pattern."""
    # Match patterns like task-abc123/main or task-abc123
    match = re.match(r"^(task-[a-zA-Z0-9_-]+)(?:/.*)?$", branch_name)
    if match:
        return match.group(1)
    return None


def get_branch_commit_info(branch_name: str, repo_path: Path) -> tuple[str | None, str | None]:
    """Get the last commit short hash and date for a branch."""
    result = run_git(
        ["log", "-1", "--format=%h|%cI", branch_name],
        repo_path,
    )
    if result.returncode != 0:
        return (None, None)

    parts = result.stdout.strip().split("|")
    if len(parts) == 2:
        return (parts[0], parts[1])
    return (None, None)


def get_worktree_branches() -> dict[str, str]:
    """Get a mapping of branch names to worktree paths."""
    worktree_branches: dict[str, str] = {}

    if not WORKTREES_BASE_DIR.exists():
        return worktree_branches

    for entry in WORKTREES_BASE_DIR.iterdir():
        if entry.is_dir():
            git_dir = entry / ".git"
            if git_dir.exists():
                result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], entry)
                if result.returncode == 0:
                    branch = result.stdout.strip()
                    worktree_branches[branch] = str(entry)

    return worktree_branches


def get_all_branches(repo_path: Path) -> list[BranchInfo]:
    """Get list of all branches with worktree indicators.

    Returns local branches with information about:
    - Whether it's the current branch
    - Whether it has an associated worktree
    - Last commit info
    """
    branches: list[BranchInfo] = []

    # Get worktree branches mapping
    worktree_branches = get_worktree_branches()

    # Get current branch
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    current_branch = result.stdout.strip() if result.returncode == 0 else ""

    # Get local branches
    result = run_git(["branch", "--format=%(refname:short)"], repo_path)
    if result.returncode != 0:
        return branches

    seen_branches: set[str] = set()

    for line in result.stdout.strip().split("\n"):
        branch_name = line.strip()
        if not branch_name or branch_name in seen_branches:
            continue

        seen_branches.add(branch_name)

        # Get commit info
        commit_short, commit_date = get_branch_commit_info(branch_name, repo_path)

        # Check for worktree
        has_worktree = branch_name in worktree_branches
        worktree_path = worktree_branches.get(branch_name)

        # Extract task ID if applicable
        task_id = extract_task_id_from_branch(branch_name)

        branches.append(
            BranchInfo(
                name=branch_name,
                is_current=branch_name == current_branch,
                has_worktree=has_worktree,
                worktree_path=worktree_path,
                task_id=task_id,
                last_commit_short=commit_short,
                last_commit_date=commit_date,
            )
        )

    # Sort: current branch first, then worktree branches, then alphabetically
    branches.sort(
        key=lambda b: (
            not b.is_current,
            not b.has_worktree,
            b.name.lower(),
        )
    )

    return branches
