"""Checkpoint library for st CLI.

Provides git+database checkpoint operations for safe task rollback.
Used by st claim, st done, st abandon, and st checkpoints commands.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class SnapshotMeta:
    """Metadata for a task checkpoint snapshot."""

    task_id: str
    project_id: str
    snapshot_path: str
    base_branch: str
    created_at: str  # ISO format
    claimed_by: str
    worktree_path: str | None = None  # Path to isolated worktree
    backend_port: int | None = None  # Allocated backend port for worktree
    frontend_port: int | None = None  # Allocated frontend port for worktree

    def to_dict(self) -> dict[str, str | int | None]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str | int | None]) -> SnapshotMeta:
        """Create from dictionary."""
        # Handle older snapshots without worktree_path
        if "worktree_path" not in data:
            data["worktree_path"] = None
        # Handle older snapshots without port info
        if "backend_port" not in data:
            data["backend_port"] = None
        if "frontend_port" not in data:
            data["frontend_port"] = None
        return cls(**data)


def _get_snapshots_dir() -> Path:
    """Get the .st/snapshots directory, creating if needed."""
    snapshots_dir = Path.cwd() / ".st" / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Ensure .st/.gitignore ignores snapshots
    gitignore = Path.cwd() / ".st" / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("snapshots/\n")
    elif "snapshots/" not in gitignore.read_text():
        with gitignore.open("a") as f:
            f.write("snapshots/\n")

    return snapshots_dir


def _get_database_url() -> str:
    """Get PostgreSQL connection string from environment."""
    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if not url:
        print("Error: DATABASE_URL or POSTGRES_URL not set", file=sys.stderr)
        sys.exit(1)
    return url


def _get_claimed_by() -> str:
    """Get the claimer identity from env or git config."""
    # Try AGENT_ID first (for agent workflows)
    agent_id = os.getenv("AGENT_ID")
    if agent_id:
        return agent_id

    # Fall back to git user
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or "unknown"
    except subprocess.CalledProcessError:
        return "unknown"


def _get_current_branch() -> str:
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "main"


def _is_working_tree_clean() -> bool:
    """Check if git working tree is clean."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        return len(result.stdout.strip()) == 0
    except subprocess.CalledProcessError:
        return False


def _get_snapshot_path(task_id: str) -> Path:
    """Get path for task snapshot SQL file."""
    return _get_snapshots_dir() / f"{task_id}.sql"


def _get_meta_path(task_id: str) -> Path:
    """Get path for task snapshot metadata file."""
    return _get_snapshots_dir() / f"{task_id}.meta.json"


def create_task_snapshot(
    task_id: str, project_id: str, use_worktree: bool = True
) -> SnapshotMeta:
    """Create DB snapshot and worktree for task.

    Creates pg_dump snapshot, metadata file, and isolated git worktree.
    The worktree provides code isolation at ~/.summitflow/worktrees/<task-id>/.
    Also allocates isolated ports for worktree services (backend/frontend).

    Args:
        task_id: Task identifier
        project_id: Project identifier
        use_worktree: Whether to create isolated worktree (default True)

    Returns:
        SnapshotMeta with checkpoint details including worktree path and ports

    Raises:
        SystemExit: On pg_dump failure or git errors
    """
    from .port_manager import allocate_ports
    from .worktree import WorktreeError, create_worktree, get_worktree_info

    snapshot_path = _get_snapshot_path(task_id)
    meta_path = _get_meta_path(task_id)
    db_url = _get_database_url()
    base_branch = _get_current_branch()

    # Check for existing snapshot
    if snapshot_path.exists():
        print(f"Error: Snapshot already exists for {task_id}", file=sys.stderr)
        print("Use 'st abandon' to remove existing checkpoint first.", file=sys.stderr)
        sys.exit(1)

    # Run pg_dump
    try:
        subprocess.run(
            [
                "pg_dump",
                "--format=custom",
                f"--file={snapshot_path}",
                db_url,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: pg_dump failed: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("Error: pg_dump not found. Install PostgreSQL client tools.", file=sys.stderr)
        sys.exit(1)

    worktree_path: str | None = None
    backend_port: int | None = None
    frontend_port: int | None = None

    if use_worktree:
        # Create isolated worktree for task
        try:
            worktree_info = create_worktree(task_id, base_branch)
            worktree_path = str(worktree_info.path)
            print(f"Created worktree: {worktree_path}")

            # Allocate isolated ports for worktree services
            ports = allocate_ports(task_id)
            backend_port = ports.backend_port
            frontend_port = ports.frontend_port
            print(f"Allocated ports: backend={backend_port}, frontend={frontend_port}")
        except WorktreeError as e:
            # Clean up snapshot on worktree failure
            snapshot_path.unlink(missing_ok=True)
            print(f"Error: Failed to create worktree: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Legacy mode: create branch in main repo
        task_branch = f"{task_id}/main"
        try:
            subprocess.run(
                ["git", "checkout", "-b", task_branch],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            # Clean up snapshot on git failure
            snapshot_path.unlink(missing_ok=True)
            print(f"Error: Failed to create git branch: {e.stderr}", file=sys.stderr)
            sys.exit(1)

    # Create metadata
    meta = SnapshotMeta(
        task_id=task_id,
        project_id=project_id,
        snapshot_path=str(snapshot_path),
        base_branch=base_branch,
        created_at=datetime.now(UTC).isoformat(),
        claimed_by=_get_claimed_by(),
        worktree_path=worktree_path,
        backend_port=backend_port,
        frontend_port=frontend_port,
    )
    meta_path.write_text(json.dumps(meta.to_dict(), indent=2))

    return meta


def restore_task_snapshot(task_id: str) -> bool:
    """DANGEROUS: Restore DB from snapshot - DESTROYS ALL DATA created after snapshot.

    WARNING: This function runs pg_restore --clean which DELETES all records
    created after the snapshot was taken. This includes:
    - Tasks created by other processes
    - User data entered during the task
    - Any database changes made after checkpoint

    DO NOT USE for normal task abandonment. Use the safe `st abandon` command
    which marks tasks as 'abandoned' without restoring the database.

    Only use this for disaster recovery when you intentionally want to
    restore the entire database to a previous state.

    Stops backend service, restores from pg_dump, restarts backend.

    Args:
        task_id: Task identifier

    Returns:
        True on success

    Raises:
        SystemExit: On restore failure
    """
    snapshot_path = _get_snapshot_path(task_id)
    meta_path = _get_meta_path(task_id)

    if not snapshot_path.exists():
        print(f"Error: No snapshot found for {task_id}", file=sys.stderr)
        sys.exit(1)

    # Load metadata for base branch info
    if meta_path.exists():
        meta = SnapshotMeta.from_dict(json.loads(meta_path.read_text()))
        base_branch = meta.base_branch
    else:
        base_branch = "main"

    db_url = _get_database_url()

    # Stop backend service
    print("Stopping summitflow-backend service...")
    try:
        subprocess.run(
            ["systemctl", "--user", "stop", "summitflow-backend"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to stop service: {e.stderr}", file=sys.stderr)

    # Restore from snapshot
    print(f"Restoring database from {snapshot_path}...")
    try:
        subprocess.run(
            [
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",  # Skip ownership issues
                "--no-privileges",  # Skip privilege issues
                f"--dbname={db_url}",
                str(snapshot_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        # pg_restore returns non-zero for warnings too
        # Only fail on critical errors, not ownership/privilege warnings
        stderr_lower = e.stderr.lower()
        # Critical errors that indicate data loss
        critical_errors = ["fatal:", "could not connect", "database does not exist"]
        if any(err in stderr_lower for err in critical_errors):
            print(f"Error: pg_restore failed: {e.stderr}", file=sys.stderr)
            # Try to restart backend even on failure
            subprocess.run(
                ["systemctl", "--user", "start", "summitflow-backend"],
                capture_output=True,
            )
            sys.exit(1)
        # Non-critical warnings (ownership, privileges, extensions)
        if e.stderr.strip():
            print("pg_restore completed with warnings (non-critical)", file=sys.stderr)

    # Restart backend service
    print("Restarting summitflow-backend service...")
    try:
        subprocess.run(
            ["systemctl", "--user", "start", "summitflow-backend"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to start service: {e.stderr}", file=sys.stderr)

    # Wait for backend to be ready (up to 30 seconds)
    print("Waiting for backend to be ready...")
    for _ in range(30):
        try:
            req = urllib.request.Request("http://localhost:8001/health", method="GET")
            with urllib.request.urlopen(req, timeout=1):
                print("Backend ready.")
                break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    else:
        print("Warning: Backend may not be fully ready yet", file=sys.stderr)

    # Checkout base branch and discard uncommitted changes
    print(f"Switching to {base_branch} branch...")
    try:
        subprocess.run(
            ["git", "checkout", base_branch],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "checkout", "."],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to checkout {base_branch}: {e.stderr}", file=sys.stderr)

    return True


def remove_snapshot(task_id: str, remove_worktree: bool = True) -> bool:
    """Delete snapshot files and optionally worktree after completion.

    Args:
        task_id: Task identifier
        remove_worktree: Whether to also remove the worktree (default True)

    Returns:
        True on success
    """
    from .worktree import remove_worktree as rm_worktree

    snapshot_path = _get_snapshot_path(task_id)
    meta_path = _get_meta_path(task_id)

    # Remove worktree if it exists
    if remove_worktree:
        try:
            rm_worktree(task_id, delete_branch=False)  # Branch handled separately
        except Exception:
            pass  # Best effort cleanup

    snapshot_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)

    return True


def create_subtask_branch(task_id: str, subtask_id: str) -> str:
    """Create git branch for subtask.

    Branch name format: {task_id}/{subtask_id}

    Args:
        task_id: Parent task identifier
        subtask_id: Subtask identifier (e.g., "1.1")

    Returns:
        Branch name created

    Raises:
        SystemExit: On git failure
    """
    branch_name = f"{task_id}/{subtask_id}"

    try:
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to create branch {branch_name}: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    return branch_name


def merge_subtask_branch(task_id: str, subtask_id: str) -> bool:
    """Merge subtask branch to task branch.

    Args:
        task_id: Parent task identifier
        subtask_id: Subtask identifier

    Returns:
        True on success

    Raises:
        SystemExit: On merge failure
    """
    from .worktree import get_worktree_info, remove_worktree

    subtask_branch = f"{task_id}/{subtask_id}"
    task_branch = f"{task_id}/main"

    # Remove worktree if it exists (so we can checkout the branch)
    # Keep the branch - we need it for the merge
    worktree_info = get_worktree_info(task_id)
    if worktree_info:
        print(f"Removing worktree before merge: {worktree_info.path}")
        remove_worktree(task_id, delete_branch=False)

    # Checkout task branch
    try:
        subprocess.run(
            ["git", "checkout", task_branch],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to checkout {task_branch}: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    # Merge subtask branch
    try:
        subprocess.run(
            ["git", "merge", "--no-ff", subtask_branch, "-m", f"Merge subtask {subtask_id}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to merge {subtask_branch}: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    # Delete subtask branch
    try:
        subprocess.run(
            ["git", "branch", "-d", subtask_branch],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to delete {subtask_branch}: {e.stderr}", file=sys.stderr)

    return True


def merge_task_branch(task_id: str) -> bool:
    """Merge task branch to main and clean up.

    Args:
        task_id: Task identifier

    Returns:
        True on success

    Raises:
        SystemExit: On merge failure
    """
    from .worktree import get_worktree_info, remove_worktree

    meta_path = _get_meta_path(task_id)

    # Get base branch from metadata
    if meta_path.exists():
        meta = SnapshotMeta.from_dict(json.loads(meta_path.read_text()))
        base_branch = meta.base_branch
    else:
        base_branch = "main"

    # Remove worktree if it exists (clean up before merge)
    # Keep the branch - we need it for the merge
    worktree_info = get_worktree_info(task_id)
    if worktree_info:
        print(f"Removing worktree before merge: {worktree_info.path}")
        remove_worktree(task_id, delete_branch=False)

    # Checkout base branch
    try:
        subprocess.run(
            ["git", "checkout", base_branch],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to checkout {base_branch}: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    # Merge task branch (task_id/main)
    task_branch = f"{task_id}/main"
    try:
        subprocess.run(
            ["git", "merge", "--no-ff", task_branch, "-m", f"Merge task {task_id}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to merge {task_branch}: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    # Delete task branch
    try:
        subprocess.run(
            ["git", "branch", "-d", task_branch],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to delete branch {task_branch}: {e.stderr}", file=sys.stderr)

    return True


def delete_subtask_branch(task_id: str, subtask_id: str) -> bool:
    """Delete subtask branch without merging.

    Used when abandoning a subtask.

    Args:
        task_id: Parent task identifier
        subtask_id: Subtask identifier

    Returns:
        True on success
    """
    branch_name = f"{task_id}/{subtask_id}"
    task_branch = f"{task_id}/main"

    # Make sure we're not on the branch we're deleting
    current = _get_current_branch()
    if current == branch_name:
        with contextlib.suppress(subprocess.CalledProcessError):
            subprocess.run(
                ["git", "checkout", task_branch],
                check=True,
                capture_output=True,
                text=True,
            )

    # Force delete the branch
    try:
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to delete {branch_name}: {e.stderr}", file=sys.stderr)
        return False

    return True


def delete_task_branches(task_id: str) -> bool:
    """Delete task branch and all subtask branches.

    Used when abandoning a task completely.

    Args:
        task_id: Task identifier

    Returns:
        True on success
    """
    meta_path = _get_meta_path(task_id)

    # Get base branch from metadata
    if meta_path.exists():
        meta = SnapshotMeta.from_dict(json.loads(meta_path.read_text()))
        base_branch = meta.base_branch
    else:
        base_branch = "main"

    with contextlib.suppress(subprocess.CalledProcessError):
        subprocess.run(
            ["git", "checkout", base_branch],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "checkout", "."],
            check=True,
            capture_output=True,
            text=True,
        )

    # List and delete all task-related branches
    try:
        result = subprocess.run(
            ["git", "branch", "--list", f"{task_id}*"],
            capture_output=True,
            text=True,
            check=True,
        )
        branches = [b.strip().lstrip("* ") for b in result.stdout.splitlines() if b.strip()]

        for branch in branches:
            try:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                print(f"Deleted branch: {branch}")
            except subprocess.CalledProcessError as e:
                print(f"Warning: Failed to delete {branch}: {e.stderr}", file=sys.stderr)

    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to list branches: {e.stderr}", file=sys.stderr)

    return True


def get_active_checkpoints(project_id: str | None = None) -> list[SnapshotMeta]:
    """List all active checkpoints.

    Args:
        project_id: Optional filter by project

    Returns:
        List of SnapshotMeta for active checkpoints
    """
    snapshots_dir = Path.cwd() / ".st" / "snapshots"
    if not snapshots_dir.exists():
        return []

    checkpoints = []
    for meta_file in snapshots_dir.glob("*.meta.json"):
        try:
            meta = SnapshotMeta.from_dict(json.loads(meta_file.read_text()))
            if project_id is None or meta.project_id == project_id:
                checkpoints.append(meta)
        except (json.JSONDecodeError, KeyError):
            continue

    # Sort by creation time, newest first
    checkpoints.sort(key=lambda m: m.created_at, reverse=True)
    return checkpoints


def has_active_task(project_id: str) -> str | None:
    """Check if a task is already claimed for a project.

    Returns the task_id if one exists, else None.
    """
    checkpoints = get_active_checkpoints(project_id)
    return checkpoints[0].task_id if checkpoints else None


def get_snapshot_info(task_id: str) -> dict[str, str | int | None] | None:
    """Get snapshot info for a task.

    Returns dict with snapshot details or None if not found.
    Includes worktree_path, worktree_exists for isolation status,
    and allocated ports for worktree services.
    """
    from .port_manager import get_worktree_ports
    from .worktree import get_worktree_info

    meta_path = _get_meta_path(task_id)
    snapshot_path = _get_snapshot_path(task_id)

    if not meta_path.exists():
        return None

    meta = SnapshotMeta.from_dict(json.loads(meta_path.read_text()))
    info = meta.to_dict()

    # Add size info
    if snapshot_path.exists():
        size_bytes = snapshot_path.stat().st_size
        if size_bytes < 1024:
            info["size"] = f"{size_bytes}B"
        elif size_bytes < 1024 * 1024:
            info["size"] = f"{size_bytes // 1024}KB"
        else:
            info["size"] = f"{size_bytes // (1024 * 1024)}MB"
    else:
        info["size"] = "0"

    # Check worktree status
    worktree_info = get_worktree_info(task_id)
    info["worktree_exists"] = str(worktree_info is not None).lower()
    if worktree_info:
        info["worktree_branch"] = worktree_info.branch

    # Add port info (from ports.json or meta)
    ports = get_worktree_ports(task_id)
    if ports:
        info["backend_port"] = ports.backend_port
        info["frontend_port"] = ports.frontend_port
        info["api_url"] = ports.api_url
        info["frontend_url"] = ports.frontend_url

    return info
