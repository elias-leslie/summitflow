"""Git Worktree Manager for Autonomous Task Execution.

Provides isolated execution environments for autonomous agents by managing
git worktrees. Each task gets its own worktree, ensuring the main repository
remains untouched until explicit merge.

See docs/worktree-design.md for architecture details.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)


class WorktreeError(Exception):
    """Error during worktree operations."""

    pass


@dataclass
class WorktreeInfo:
    """Information about a task's worktree."""

    path: Path
    branch: str
    task_id: str
    project_id: str
    base_branch: str
    is_active: bool = True
    commit_count: int = 0
    files_changed: int = 0
    additions: int = 0
    deletions: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class WorktreeManager:
    """Manages git worktrees for autonomous task execution.

    Each task gets its own worktree at:
        /tmp/summitflow-worktrees/{project_id}/{task_id}/

    With a corresponding branch:
        exec/{task_id}

    This allows:
    1. Multiple tasks to execute simultaneously
    2. Each task's changes are isolated from main
    3. Branches persist until explicitly merged
    4. Clear 1:1:1 mapping: task → worktree → branch

    Security:
    - All IDs are sanitized to prevent path traversal attacks
    - Only alphanumeric, hyphen, and underscore characters are allowed
    """

    WORKTREE_BASE_DIR = Path(os.getenv("WORKTREE_BASE_DIR", "/tmp/summitflow-worktrees"))
    BRANCH_PREFIX = "exec"
    # Pattern for valid IDs: alphanumeric, hyphen, underscore only
    VALID_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

    def __init__(self, project_dir: Path, base_branch: str | None = None):
        """Initialize WorktreeManager.

        Args:
            project_dir: Path to the project's git repository
            base_branch: Branch to base worktrees on (auto-detects if not provided)
        """
        self.project_dir = Path(project_dir)
        self.base_branch = base_branch or self._detect_base_branch()
        self._merge_locks: dict[str, asyncio.Lock] = {}

    def _detect_base_branch(self) -> str:
        """Detect the base branch for worktree creation.

        Priority order:
        1. DEFAULT_BRANCH environment variable
        2. Auto-detect main/master (if they exist)
        3. Fall back to current branch

        Returns:
            The detected base branch name
        """
        # 1. Check for DEFAULT_BRANCH env var
        env_branch = os.getenv("DEFAULT_BRANCH")
        if env_branch:
            result = self._run_git(["rev-parse", "--verify", env_branch])
            if result.returncode == 0:
                return env_branch
            logger.warning(
                "default_branch_not_found",
                branch=env_branch,
                msg="DEFAULT_BRANCH not found, auto-detecting",
            )

        # 2. Auto-detect main/master
        for branch in ["main", "master"]:
            result = self._run_git(["rev-parse", "--verify", branch])
            if result.returncode == 0:
                return branch

        # 3. Fall back to current branch
        current = self._get_current_branch()
        logger.warning(
            "using_current_branch",
            branch=current,
            msg="Could not find main/master, using current branch",
        )
        return current

    def _get_current_branch(self) -> str:
        """Get the current git branch."""
        result = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        if result.returncode != 0:
            raise WorktreeError(f"Failed to get current branch: {result.stderr}")
        return result.stdout.strip()

    def _sanitize_id(self, id_value: str, id_type: str = "ID") -> str:
        """Sanitize an ID to prevent path traversal and injection attacks.

        Args:
            id_value: The raw ID value to sanitize
            id_type: Description for error messages (e.g., "task_id", "project_id")

        Returns:
            The sanitized ID

        Raises:
            WorktreeError: If the ID contains invalid characters
        """
        # Remove null bytes
        id_value = id_value.replace("\x00", "")

        # Check for path traversal attempts
        if ".." in id_value or "/" in id_value or "\\" in id_value:
            raise WorktreeError(
                f"Invalid {id_type}: path traversal characters not allowed: {id_value!r}"
            )

        # Check for valid characters only
        if not self.VALID_ID_PATTERN.match(id_value):
            raise WorktreeError(
                f"Invalid {id_type}: only alphanumeric, hyphen, and underscore allowed: {id_value!r}"
            )

        return id_value

    def _run_git(
        self, args: list[str], cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command and return the result."""
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def _get_worktree_dir(self, project_id: str) -> Path:
        """Get the worktrees directory for a project.

        Args:
            project_id: The project ID (will be sanitized)
        """
        safe_project_id = self._sanitize_id(project_id, "project_id")
        return self.WORKTREE_BASE_DIR / safe_project_id

    def get_worktree_path(self, project_id: str, task_id: str) -> Path:
        """Get the worktree path for a task.

        Args:
            project_id: The project ID (will be sanitized)
            task_id: The task ID (will be sanitized)

        Returns:
            Path to the worktree directory

        Raises:
            WorktreeError: If IDs contain invalid characters
        """
        safe_task_id = self._sanitize_id(task_id, "task_id")
        return self._get_worktree_dir(project_id) / safe_task_id

    def get_branch_name(self, task_id: str) -> str:
        """Get the branch name for a task.

        Args:
            task_id: The task ID (will be sanitized)

        Returns:
            The git branch name

        Raises:
            WorktreeError: If task_id contains invalid characters
        """
        safe_task_id = self._sanitize_id(task_id, "task_id")
        return f"{self.BRANCH_PREFIX}/{safe_task_id}"

    def worktree_exists(self, project_id: str, task_id: str) -> bool:
        """Check if a worktree exists for a task."""
        return self.get_worktree_path(project_id, task_id).exists()

    def get_worktree_info(self, project_id: str, task_id: str) -> WorktreeInfo | None:
        """Get info about a task's worktree.

        Args:
            project_id: The project ID
            task_id: The task ID

        Returns:
            WorktreeInfo if worktree exists, None otherwise
        """
        worktree_path = self.get_worktree_path(project_id, task_id)
        if not worktree_path.exists():
            return None

        # Verify the branch exists in the worktree
        result = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree_path)
        if result.returncode != 0:
            return None

        actual_branch = result.stdout.strip()
        stats = self._get_worktree_stats(worktree_path)

        return WorktreeInfo(
            path=worktree_path,
            branch=actual_branch,
            task_id=task_id,
            project_id=project_id,
            base_branch=self.base_branch,
            is_active=True,
            commit_count=stats["commit_count"],
            files_changed=stats["files_changed"],
            additions=stats["additions"],
            deletions=stats["deletions"],
        )

    def _get_worktree_stats(self, worktree_path: Path) -> dict[str, int]:
        """Get diff statistics for a worktree."""
        stats = {
            "commit_count": 0,
            "files_changed": 0,
            "additions": 0,
            "deletions": 0,
        }

        if not worktree_path.exists():
            return stats

        # Commit count
        result = self._run_git(
            ["rev-list", "--count", f"{self.base_branch}..HEAD"], cwd=worktree_path
        )
        if result.returncode == 0:
            stats["commit_count"] = int(result.stdout.strip() or "0")

        # Diff stats
        result = self._run_git(
            ["diff", "--shortstat", f"{self.base_branch}...HEAD"], cwd=worktree_path
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse: "3 files changed, 50 insertions(+), 10 deletions(-)"
            match = re.search(r"(\d+) files? changed", result.stdout)
            if match:
                stats["files_changed"] = int(match.group(1))
            match = re.search(r"(\d+) insertions?", result.stdout)
            if match:
                stats["additions"] = int(match.group(1))
            match = re.search(r"(\d+) deletions?", result.stdout)
            if match:
                stats["deletions"] = int(match.group(1))

        return stats

    def _symlink_node_modules(self, worktree_path: Path) -> None:
        """Symlink node_modules directories from main repo to worktree.

        This enables pre-commit hooks that run eslint/tsc to find their dependencies.
        """
        # Common locations for node_modules in monorepos
        node_modules_locations = [
            "frontend/node_modules",
            "node_modules",
        ]

        for rel_path in node_modules_locations:
            source = self.project_dir / rel_path
            target = worktree_path / rel_path

            # Only create symlink if source exists and target doesn't
            if source.exists() and source.is_dir() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    target.symlink_to(source)
                    logger.debug(
                        "symlinked_node_modules",
                        source=str(source),
                        target=str(target),
                    )
                except OSError as e:
                    # Non-fatal - continue without symlink
                    logger.warning(
                        "node_modules_symlink_failed",
                        path=rel_path,
                        error=str(e),
                    )

    def create_worktree(self, project_id: str, task_id: str) -> WorktreeInfo:
        """Create a worktree for a task.

        Args:
            project_id: The project ID
            task_id: The task ID (e.g., "task-b01611e4")

        Returns:
            WorktreeInfo for the created worktree

        Raises:
            WorktreeError: If worktree creation fails or lock times out
        """
        from .file_lock import FileLockTimeout, repo_lock

        worktree_path = self.get_worktree_path(project_id, task_id)
        branch_name = self.get_branch_name(task_id)

        # Ensure parent directory exists
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        # Acquire repo lock for concurrent safety (prevents race conditions)
        try:
            with repo_lock(self.project_dir, timeout=30.0):
                # Step 1: Prune stale worktree entries first (handles manually deleted directories)
                self._run_git(["worktree", "prune"])

                # Step 2: Try git worktree remove if path exists
                if worktree_path.exists():
                    logger.info(
                        "removing_existing_worktree",
                        path=str(worktree_path),
                        task_id=task_id,
                    )
                    result = self._run_git(["worktree", "remove", "--force", str(worktree_path)])

                    # Step 3: If git worktree remove failed (not a proper worktree), force delete
                    if result.returncode != 0:
                        logger.warning(
                            "worktree_remove_failed_forcing",
                            task_id=task_id,
                            error=result.stderr,
                        )
                        shutil.rmtree(worktree_path, ignore_errors=True)

                # Step 4: Delete branch if it exists (from previous attempt or stale)
                self._run_git(["branch", "-D", branch_name])

                # Create worktree with new branch from base
                result = self._run_git(
                    [
                        "worktree",
                        "add",
                        "-b",
                        branch_name,
                        str(worktree_path),
                        self.base_branch,
                    ]
                )

                if result.returncode != 0:
                    raise WorktreeError(f"Failed to create worktree for {task_id}: {result.stderr}")

        except FileLockTimeout as e:
            raise WorktreeError(f"Timed out waiting for repo lock: {e}") from e

        # Symlink node_modules for frontend projects (needed for pre-commit hooks)
        self._symlink_node_modules(worktree_path)

        logger.info(
            "worktree_created",
            task_id=task_id,
            project_id=project_id,
            branch=branch_name,
            path=str(worktree_path),
        )

        return WorktreeInfo(
            path=worktree_path,
            branch=branch_name,
            task_id=task_id,
            project_id=project_id,
            base_branch=self.base_branch,
            is_active=True,
        )

    def get_or_create_worktree(self, project_id: str, task_id: str) -> WorktreeInfo:
        """Get existing worktree or create a new one for a task.

        Args:
            project_id: The project ID
            task_id: The task ID

        Returns:
            WorktreeInfo for the worktree
        """
        existing = self.get_worktree_info(project_id, task_id)
        if existing:
            logger.info(
                "using_existing_worktree",
                task_id=task_id,
                path=str(existing.path),
            )
            return existing

        return self.create_worktree(project_id, task_id)

    def remove_worktree(self, project_id: str, task_id: str, delete_branch: bool = True) -> None:
        """Remove a task's worktree.

        Args:
            project_id: The project ID
            task_id: The task ID
            delete_branch: Whether to also delete the branch
        """
        worktree_path = self.get_worktree_path(project_id, task_id)
        branch_name = self.get_branch_name(task_id)

        if worktree_path.exists():
            result = self._run_git(["worktree", "remove", "--force", str(worktree_path)])
            if result.returncode == 0:
                logger.info(
                    "worktree_removed",
                    task_id=task_id,
                    path=str(worktree_path),
                )
            else:
                logger.warning(
                    "worktree_remove_failed",
                    task_id=task_id,
                    error=result.stderr,
                )
                # Force remove directory if git command fails
                shutil.rmtree(worktree_path, ignore_errors=True)

        if delete_branch:
            self._run_git(["branch", "-D", branch_name])
            logger.info("branch_deleted", branch=branch_name)

        # Prune any stale worktree entries
        self._run_git(["worktree", "prune"])

    def commit_in_worktree(
        self, project_id: str, task_id: str, message: str, max_retries: int = 2
    ) -> bool:
        """Commit all changes in a task's worktree.

        Handles pre-commit hooks that modify files by re-staging and retrying.

        Args:
            project_id: The project ID
            task_id: The task ID
            message: Commit message
            max_retries: Max retry attempts if hooks modify files

        Returns:
            True if commit succeeded or nothing to commit
        """
        worktree_path = self.get_worktree_path(project_id, task_id)
        if not worktree_path.exists():
            logger.warning("commit_no_worktree", task_id=task_id)
            return False

        for attempt in range(max_retries + 1):
            # Stage all changes
            self._run_git(["add", "."], cwd=worktree_path)

            # Commit
            result = self._run_git(["commit", "-m", message], cwd=worktree_path)

            if result.returncode == 0:
                logger.info("commit_success", task_id=task_id, message=message[:50])
                return True
            elif "nothing to commit" in result.stdout + result.stderr:
                logger.info("commit_nothing_to_commit", task_id=task_id)
                return True
            elif "files were modified by this hook" in result.stderr and attempt < max_retries:
                # Pre-commit hooks modified files, retry with re-staged changes
                logger.info(
                    "commit_retry_after_hooks",
                    task_id=task_id,
                    attempt=attempt + 1,
                )
                continue
            else:
                logger.error("commit_failed", task_id=task_id, error=result.stderr)
                return False

        return False

    async def merge_worktree(
        self,
        project_id: str,
        task_id: str,
        delete_after: bool = True,
        no_commit: bool = False,
    ) -> bool:
        """Merge a task's worktree branch back to base branch.

        Args:
            project_id: The project ID
            task_id: The task ID
            delete_after: Whether to remove worktree and branch after merge
            no_commit: If True, stage changes but don't commit (for review)

        Returns:
            True if merge succeeded
        """
        info = self.get_worktree_info(project_id, task_id)
        if not info:
            logger.warning("merge_no_worktree", task_id=task_id)
            return False

        # Serialize merges per project
        lock = self._merge_locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            return self._do_merge(info, delete_after, no_commit)

    def _do_merge(self, info: WorktreeInfo, delete_after: bool, no_commit: bool) -> bool:
        """Execute the merge operation (called under lock)."""
        logger.info(
            "merge_starting",
            task_id=info.task_id,
            branch=info.branch,
            base=self.base_branch,
            no_commit=no_commit,
        )

        # Switch to base branch in main project
        result = self._run_git(["checkout", self.base_branch])
        if result.returncode != 0:
            logger.error(
                "merge_checkout_failed",
                base=self.base_branch,
                error=result.stderr,
            )
            return False

        # Merge the task branch
        merge_args = ["merge", "--no-ff", info.branch]
        if no_commit:
            merge_args.append("--no-commit")
        else:
            merge_args.extend(["-m", f"auto: Merge {info.branch}"])

        result = self._run_git(merge_args)

        if result.returncode != 0:
            logger.error(
                "merge_conflict",
                task_id=info.task_id,
                error=result.stderr,
            )
            self._run_git(["merge", "--abort"])
            return False

        if no_commit:
            logger.info(
                "merge_staged",
                task_id=info.task_id,
                msg="Changes staged, ready for review",
            )
        else:
            logger.info("merge_success", task_id=info.task_id, branch=info.branch)

        if delete_after:
            self.remove_worktree(info.project_id, info.task_id, delete_branch=True)

        return True

    def list_active_worktrees(self, project_id: str | None = None) -> list[WorktreeInfo]:
        """List all active worktrees.

        Args:
            project_id: If provided, only list worktrees for this project

        Returns:
            List of WorktreeInfo for active worktrees
        """
        worktrees: list[WorktreeInfo] = []

        if not self.WORKTREE_BASE_DIR.exists():
            return worktrees

        # Iterate projects
        project_dirs = (
            [self.WORKTREE_BASE_DIR / project_id]
            if project_id
            else list(self.WORKTREE_BASE_DIR.iterdir())
        )

        for project_dir in project_dirs:
            if not project_dir.is_dir():
                continue

            pid = project_dir.name

            # Iterate task worktrees
            for task_dir in project_dir.iterdir():
                if not task_dir.is_dir():
                    continue

                tid = task_dir.name
                info = self.get_worktree_info(pid, tid)
                if info:
                    worktrees.append(info)

        return worktrees

    # Default cleanup age: 30 days in hours
    DEFAULT_CLEANUP_AGE_DAYS = 30

    def cleanup_stale_worktrees(
        self,
        max_age_days: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, list[dict[str, Any]]]:
        """Remove worktrees older than max_age_days.

        Args:
            max_age_days: Maximum age in days before cleanup (default 30)
            dry_run: If True, only report what would be removed

        Returns:
            Dict with 'removed' list (or 'would_remove' if dry_run) of worktree info
        """
        if max_age_days is None:
            max_age_days = self.DEFAULT_CLEANUP_AGE_DAYS

        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        result: dict[str, list[dict[str, Any]]] = {
            "removed": [],
            "would_remove": [],
        }
        key = "would_remove" if dry_run else "removed"

        if not self.WORKTREE_BASE_DIR.exists():
            return result

        for project_dir in self.WORKTREE_BASE_DIR.iterdir():
            if not project_dir.is_dir():
                continue

            for task_dir in project_dir.iterdir():
                if not task_dir.is_dir():
                    continue

                # Check modification time
                mtime = datetime.fromtimestamp(task_dir.stat().st_mtime, tz=UTC)
                if mtime < cutoff:
                    age_days = (datetime.now(UTC) - mtime).total_seconds() / 86400
                    worktree_info = {
                        "project_id": project_dir.name,
                        "task_id": task_dir.name,
                        "path": str(task_dir),
                        "age_days": round(age_days, 1),
                        "last_modified": mtime.isoformat(),
                    }

                    if dry_run:
                        logger.info(
                            "cleanup_would_remove",
                            project=project_dir.name,
                            task=task_dir.name,
                            age_days=age_days,
                        )
                    else:
                        logger.info(
                            "cleanup_stale_worktree",
                            project=project_dir.name,
                            task=task_dir.name,
                            age_days=age_days,
                        )
                        self.remove_worktree(project_dir.name, task_dir.name, delete_branch=True)

                    result[key].append(worktree_info)

        # Also prune any orphaned worktree entries (unless dry run)
        if not dry_run:
            self._run_git(["worktree", "prune"])

        return result

    def get_worktree_count_warning(
        self,
        warning_threshold: int = 10,
        critical_threshold: int = 25,
    ) -> dict[str, int | str | None]:
        """Check if worktree count exceeds thresholds.

        Args:
            warning_threshold: Count at which to warn
            critical_threshold: Count at which to flag critical

        Returns:
            Dict with count, level (None, 'warning', 'critical'), and message
        """
        worktrees = self.list_active_worktrees()
        count = len(worktrees)

        if count >= critical_threshold:
            level = "critical"
            message = (
                f"Critical: {count} worktrees exist (threshold: {critical_threshold}). Run cleanup."
            )
        elif count >= warning_threshold:
            level = "warning"
            message = f"Warning: {count} worktrees exist (threshold: {warning_threshold}). Consider cleanup."
        else:
            level = None
            message = None

        return {
            "count": count,
            "level": level,
            "message": message,
            "warning_threshold": warning_threshold,
            "critical_threshold": critical_threshold,
        }

    def cleanup_old_worktrees(
        self, max_age_days: int = 30, dry_run: bool = False
    ) -> dict[str, list[dict[str, Any]]]:
        """Convenience alias for cleanup_stale_worktrees with 30-day default.

        This is the primary API for cleanup - uses days instead of hours.
        Matches criterion ac-658: 30 day default, configurable.

        Args:
            max_age_days: Maximum age in days (default 30)
            dry_run: If True, only preview what would be removed

        Returns:
            Dict with removal results
        """
        return self.cleanup_stale_worktrees(max_age_days=max_age_days, dry_run=dry_run)

    # Blast radius thresholds (per d11 decision)
    BLAST_RADIUS_FILES_THRESHOLD = 5
    BLAST_RADIUS_DELETED_LINES_THRESHOLD = 100

    def check_blast_radius(self, project_id: str, task_id: str) -> dict[str, Any]:
        """Check if worktree changes exceed blast radius thresholds.

        Per d11 decision: Before merge_worktree() (PR creation), calculate
        blast radius. If files_touched > 5 OR lines_deleted > 100, flag
        for SUPERVISOR review.

        Args:
            project_id: The project ID
            task_id: The task ID

        Returns:
            Dict with:
            - passed: bool - whether changes are within thresholds
            - files_changed: int - number of files changed
            - additions: int - lines added
            - deletions: int - lines deleted
            - exceeds_files: bool - if files > threshold
            - exceeds_deletions: bool - if deletions > threshold
            - reason: str - explanation if blocked
        """
        worktree_path = self.get_worktree_path(project_id, task_id)
        if not worktree_path.exists():
            return {
                "passed": False,
                "files_changed": 0,
                "additions": 0,
                "deletions": 0,
                "exceeds_files": False,
                "exceeds_deletions": False,
                "reason": "Worktree does not exist",
            }

        stats = self._get_worktree_stats(worktree_path)

        exceeds_files = stats["files_changed"] > self.BLAST_RADIUS_FILES_THRESHOLD
        exceeds_deletions = stats["deletions"] > self.BLAST_RADIUS_DELETED_LINES_THRESHOLD

        passed = not (exceeds_files or exceeds_deletions)

        reason = ""
        if not passed:
            reasons = []
            if exceeds_files:
                reasons.append(
                    f"files_changed ({stats['files_changed']}) > threshold ({self.BLAST_RADIUS_FILES_THRESHOLD})"
                )
            if exceeds_deletions:
                reasons.append(
                    f"deletions ({stats['deletions']}) > threshold ({self.BLAST_RADIUS_DELETED_LINES_THRESHOLD})"
                )
            reason = "Blast radius exceeded: " + " AND ".join(reasons)

        if not passed:
            logger.warning(
                "blast_radius_exceeded",
                task_id=task_id,
                files_changed=stats["files_changed"],
                deletions=stats["deletions"],
                reason=reason,
            )
        else:
            logger.debug(
                "blast_radius_ok",
                task_id=task_id,
                files_changed=stats["files_changed"],
                deletions=stats["deletions"],
            )

        return {
            "passed": passed,
            "files_changed": stats["files_changed"],
            "additions": stats["additions"],
            "deletions": stats["deletions"],
            "exceeds_files": exceeds_files,
            "exceeds_deletions": exceeds_deletions,
            "reason": reason,
        }

    def reset_worktree_to_base(self, project_id: str, task_id: str) -> bool:
        """Reset a worktree to the base branch state (hard reset).

        Used by SUPERVISOR escalation to get a fresh slate - discards all
        WORKER changes and starts from clean main branch state.

        Args:
            project_id: The project ID
            task_id: The task ID

        Returns:
            True if reset succeeded
        """
        worktree_path = self.get_worktree_path(project_id, task_id)
        if not worktree_path.exists():
            logger.warning("reset_no_worktree", task_id=task_id)
            return False

        # Fetch latest from origin first
        self._run_git(["fetch", "origin", self.base_branch], cwd=worktree_path)

        # Hard reset to base branch
        result = self._run_git(
            ["reset", "--hard", f"origin/{self.base_branch}"],
            cwd=worktree_path,
        )

        if result.returncode != 0:
            # Try without origin prefix
            result = self._run_git(
                ["reset", "--hard", self.base_branch],
                cwd=worktree_path,
            )

        if result.returncode == 0:
            logger.info(
                "worktree_reset_to_base",
                task_id=task_id,
                base=self.base_branch,
            )
            return True
        else:
            logger.error(
                "worktree_reset_failed",
                task_id=task_id,
                error=result.stderr,
            )
            return False

    def check_merge_conflicts(self, project_id: str, task_id: str) -> dict[str, Any]:
        """Check if merging worktree to base would cause conflicts.

        Per d10 decision: Merge conflicts trigger SUPERVISOR escalation, NOT
        immediate human escalation.

        Does a dry-run merge to detect conflicts without actually merging.

        Args:
            project_id: The project ID
            task_id: The task ID

        Returns:
            Dict with:
            - has_conflicts: bool
            - conflicting_files: list[str] - files with conflicts
            - can_fast_forward: bool - whether merge can be fast-forwarded
        """
        worktree_path = self.get_worktree_path(project_id, task_id)
        if not worktree_path.exists():
            return {
                "has_conflicts": False,
                "conflicting_files": [],
                "can_fast_forward": False,
                "error": "Worktree does not exist",
            }

        # Fetch latest from origin
        self._run_git(["fetch", "origin", self.base_branch], cwd=worktree_path)

        # Try a dry-run merge
        result = self._run_git(
            ["merge", "--no-commit", "--no-ff", f"origin/{self.base_branch}"],
            cwd=worktree_path,
        )

        # Abort the dry-run merge
        self._run_git(["merge", "--abort"], cwd=worktree_path)

        has_conflicts = result.returncode != 0 and "CONFLICT" in result.stdout + result.stderr

        # Parse conflicting files
        conflicting_files: list[str] = []
        if has_conflicts:
            for line in (result.stdout + result.stderr).splitlines():
                # Extract filename from "CONFLICT (content): Merge conflict in <file>"
                if line.startswith("CONFLICT") and "Merge conflict in" in line:
                    parts = line.split("Merge conflict in")
                    if len(parts) > 1:
                        conflicting_files.append(parts[1].strip())

        # Check if fast-forward is possible
        can_ff_result = self._run_git(
            ["merge-base", "--is-ancestor", f"origin/{self.base_branch}", "HEAD"],
            cwd=worktree_path,
        )
        can_fast_forward = can_ff_result.returncode == 0

        if has_conflicts:
            logger.warning(
                "merge_conflicts_detected",
                task_id=task_id,
                conflicting_files=conflicting_files,
            )
        else:
            logger.debug(
                "no_merge_conflicts",
                task_id=task_id,
                can_fast_forward=can_fast_forward,
            )

        return {
            "has_conflicts": has_conflicts,
            "conflicting_files": conflicting_files,
            "can_fast_forward": can_fast_forward,
        }

    def get_conflict_context(self, project_id: str, task_id: str, file_path: str) -> dict[str, Any]:
        """Get detailed context for a merge conflict.

        Provides both sides of the conflict and file history to help
        SUPERVISOR resolve it.

        Args:
            project_id: The project ID
            task_id: The task ID
            file_path: Path to conflicting file

        Returns:
            Dict with ours, theirs, base, and file history
        """
        worktree_path = self.get_worktree_path(project_id, task_id)
        if not worktree_path.exists():
            return {"error": "Worktree does not exist"}

        context: dict[str, Any] = {
            "file_path": file_path,
            "ours": None,  # Our (worktree) version
            "theirs": None,  # Their (main) version
            "base": None,  # Common ancestor
            "history": [],  # Recent commits touching this file
        }

        # Get our version
        result = self._run_git(["show", f"HEAD:{file_path}"], cwd=worktree_path)
        if result.returncode == 0:
            context["ours"] = result.stdout

        # Get their version
        result = self._run_git(
            ["show", f"origin/{self.base_branch}:{file_path}"], cwd=worktree_path
        )
        if result.returncode == 0:
            context["theirs"] = result.stdout

        # Get merge base version
        base_result = self._run_git(
            ["merge-base", "HEAD", f"origin/{self.base_branch}"], cwd=worktree_path
        )
        if base_result.returncode == 0:
            base_sha = base_result.stdout.strip()
            result = self._run_git(["show", f"{base_sha}:{file_path}"], cwd=worktree_path)
            if result.returncode == 0:
                context["base"] = result.stdout

        # Get file history (last 5 commits touching this file)
        result = self._run_git(
            ["log", "--oneline", "-5", "--", file_path],
            cwd=worktree_path,
        )
        if result.returncode == 0:
            context["history"] = result.stdout.strip().split("\n")

        return context

    def get_changed_files(self, project_id: str, task_id: str) -> list[tuple[str, str]]:
        """Get list of changed files in a task's worktree.

        Args:
            project_id: The project ID
            task_id: The task ID

        Returns:
            List of (status, filepath) tuples
        """
        worktree_path = self.get_worktree_path(project_id, task_id)
        if not worktree_path.exists():
            return []

        result = self._run_git(
            ["diff", "--name-status", f"{self.base_branch}...HEAD"],
            cwd=worktree_path,
        )

        files: list[tuple[str, str]] = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                files.append((parts[0], parts[1]))

        return files


# Singleton instance factory
_manager_instances: dict[str, WorktreeManager] = {}


def get_worktree_manager(project_dir: Path | str) -> WorktreeManager:
    """Get or create a WorktreeManager for a project.

    Args:
        project_dir: Path to the project's git repository

    Returns:
        WorktreeManager instance
    """
    project_dir = Path(project_dir)
    key = str(project_dir.resolve())

    if key not in _manager_instances:
        _manager_instances[key] = WorktreeManager(project_dir)

    return _manager_instances[key]
