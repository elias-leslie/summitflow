"""Git utility functions."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from ..api.models.git_models import (
    BranchInfo,
    CommitInfo,
    DiffFile,
    DiffStats,
    RepoStatus,
    SnapshotInfo,
    SyncResult,
    WorktreeInfo,
)

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


# --- Diff Helpers ---


def get_task_diff(
    project_root: Path,
    pre_merge_sha: str,
    merge_sha: str,
) -> tuple[list[DiffFile], DiffStats]:
    """Get file-level diffs between two SHAs.

    Args:
        project_root: Path to the git repo
        pre_merge_sha: SHA before merge
        merge_sha: SHA after merge

    Returns:
        Tuple of (list of DiffFile, aggregate DiffStats).
    """
    sha_range = f"{pre_merge_sha}..{merge_sha}"

    # Get numstat for per-file counts
    numstat = run_git(["diff", "--numstat", sha_range], project_root)
    files: list[DiffFile] = []
    total_add = 0
    total_del = 0

    if numstat.returncode == 0:
        for line in numstat.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            adds = int(parts[0]) if parts[0] != "-" else 0
            dels = int(parts[1]) if parts[1] != "-" else 0
            path = parts[2]
            total_add += adds
            total_del += dels
            files.append(DiffFile(
                path=path,
                status="modified",
                additions=adds,
                deletions=dels,
                diff_content="",
            ))

    # Get full unified diff
    full_diff = run_git(["diff", sha_range], project_root)
    if full_diff.returncode == 0:
        _assign_diff_content(files, full_diff.stdout)

    # Detect added/deleted via diff-tree
    tree_result = run_git(
        ["diff-tree", "--no-commit-id", "-r", "--name-status", sha_range],
        project_root,
    )
    if tree_result.returncode == 0:
        status_map: dict[str, str] = {}
        for line in tree_result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                code = parts[0][0]  # A, M, D, R
                fpath = parts[-1]
                status_map[fpath] = {
                    "A": "added",
                    "M": "modified",
                    "D": "deleted",
                    "R": "renamed",
                }.get(code, "modified")
        for f in files:
            if f.path in status_map:
                f.status = status_map[f.path]

    stats = DiffStats(
        files_changed=len(files),
        additions=total_add,
        deletions=total_del,
    )
    return files, stats


def _assign_diff_content(files: list[DiffFile], full_diff: str) -> None:
    """Split a unified diff into per-file chunks and assign to DiffFile objects."""
    file_map = {f.path: f for f in files}
    current_path: str | None = None
    current_lines: list[str] = []

    for line in full_diff.split("\n"):
        if line.startswith("diff --git"):
            # Flush previous file
            if current_path and current_path in file_map:
                file_map[current_path].diff_content = "\n".join(current_lines)
            # Parse new file path: "diff --git a/path b/path"
            parts = line.split(" b/", 1)
            current_path = parts[1] if len(parts) > 1 else None
            current_lines = [line]
        else:
            current_lines.append(line)

    # Flush last file
    if current_path and current_path in file_map:
        file_map[current_path].diff_content = "\n".join(current_lines)


def get_diff_stats(project_root: Path, sha_range: str) -> DiffStats:
    """Get aggregate diff statistics for a SHA range."""
    result = run_git(["diff", "--shortstat", sha_range], project_root)
    files_count = 0
    adds = 0
    dels = 0
    if result.returncode == 0 and result.stdout.strip():
        text = result.stdout.strip()
        m = re.search(r"(\d+) file", text)
        if m:
            files_count = int(m.group(1))
        m = re.search(r"(\d+) insertion", text)
        if m:
            adds = int(m.group(1))
        m = re.search(r"(\d+) deletion", text)
        if m:
            dels = int(m.group(1))
    return DiffStats(files_changed=files_count, additions=adds, deletions=dels)


# --- Commit History Helpers ---


def get_recent_commits(repo_path: Path, limit: int = 30) -> list[CommitInfo]:
    """Get recent commits from a repository.

    Args:
        repo_path: Path to the git repo
        limit: Maximum number of commits to return

    Returns:
        List of CommitInfo objects.
    """
    result = run_git(
        [
            "log",
            f"-n{limit}",
            "--format=COMMIT_START%n%H%n%h%n%s%n%an%n%ae%n%cI",
            "--numstat",
        ],
        repo_path,
    )
    if result.returncode != 0:
        return []

    commits: list[CommitInfo] = []
    repo_name = repo_path.name
    blocks = result.stdout.split("COMMIT_START\n")

    for block in blocks:
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        if len(lines) < 6:
            continue

        sha = lines[0]
        short_sha = lines[1]
        message = lines[2]
        author_name = lines[3]
        author_email = lines[4]
        date = lines[5]

        # Parse numstat lines (remaining lines after the 6 header lines)
        files_changed = 0
        insertions = 0
        deletions = 0
        for stat_line in lines[6:]:
            if not stat_line.strip():
                continue
            parts = stat_line.split("\t")
            if len(parts) == 3:
                files_changed += 1
                insertions += int(parts[0]) if parts[0] != "-" else 0
                deletions += int(parts[1]) if parts[1] != "-" else 0

        commits.append(CommitInfo(
            sha=sha,
            short_sha=short_sha,
            message=message,
            author_name=author_name,
            author_email=author_email,
            date=date,
            repo_name=repo_name,
            files_changed=files_changed,
            insertions=insertions,
            deletions=deletions,
        ))

    return commits


# --- Snapshot Helpers ---


def list_snapshots(repo_path: Path) -> list[SnapshotInfo]:
    """List pre-merge snapshot tags from a repository.

    Args:
        repo_path: Path to the git repo

    Returns:
        List of SnapshotInfo objects.
    """
    result = run_git(
        ["tag", "-l", "snapshot/pre-merge/*", "--sort=-creatordate",
         "--format=%(refname:short)\t%(objectname)\t%(objectname:short)\t%(creatordate:iso-strict)"],
        repo_path,
    )
    if result.returncode != 0:
        return []

    # Get current HEAD
    head_result = run_git(["rev-parse", "HEAD"], repo_path)
    head_sha = head_result.stdout.strip() if head_result.returncode == 0 else ""

    repo_name = repo_path.name
    snapshots: list[SnapshotInfo] = []

    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue

        tag_name = parts[0]  # snapshot/pre-merge/{task_id}
        sha = parts[1]
        short_sha = parts[2]
        created_at = parts[3]

        # Extract task_id from tag name
        task_id = tag_name.replace("snapshot/pre-merge/", "")

        # Count commits ahead
        ahead_result = run_git(
            ["rev-list", "--count", f"{sha}..HEAD"],
            repo_path,
        )
        commits_ahead = (
            int(ahead_result.stdout.strip())
            if ahead_result.returncode == 0
            else 0
        )

        snapshots.append(SnapshotInfo(
            task_id=task_id,
            task_title="",  # Populated by API endpoint from DB
            sha=sha,
            short_sha=short_sha,
            created_at=created_at,
            project_id="",  # Populated by API endpoint
            repo_name=repo_name,
            is_current=sha == head_sha,
            commits_ahead=commits_ahead,
        ))

    return snapshots


def revert_to_snapshot(repo_path: Path, sha: str, commits_ahead: int) -> str | None:
    """Revert HEAD to a snapshot point using git revert (preserves history).

    Args:
        repo_path: Path to the git repo
        sha: The snapshot SHA to revert to
        commits_ahead: Number of commits to revert

    Returns:
        The new HEAD SHA, or None on failure.
    """
    if commits_ahead <= 0:
        return None

    # Revert the range of commits (newest first)
    result = run_git(
        ["revert", "--no-edit", f"HEAD~{commits_ahead}..HEAD"],
        repo_path,
    )
    if result.returncode != 0:
        # Abort the revert on failure
        run_git(["revert", "--abort"], repo_path)
        return None

    # Return the new HEAD
    head_result = run_git(["rev-parse", "HEAD"], repo_path)
    return head_result.stdout.strip() if head_result.returncode == 0 else None
