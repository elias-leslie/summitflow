"""Git branch operations for checkpoint system.

Handles creation, merging, and deletion of task and subtask branches.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys

from .checkpoint_metadata import load_snapshot_meta


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


def merge_subtask_branch(task_id: str, subtask_id: str, project_id: str | None = None) -> bool:
    """Merge subtask branch to task branch (if subtask branch exists).

    This merges WITHIN the worktree context - does NOT remove the worktree.
    The worktree stays alive until the entire task is completed.

    Args:
        task_id: Parent task identifier
        subtask_id: Subtask identifier
        project_id: Project identifier for per-project worktree paths

    Returns:
        True on success, False if no subtask branch exists
    """
    from .worktree import get_worktree_info

    subtask_branch = f"{task_id}/{subtask_id}"
    task_branch = f"{task_id}/main"

    # Get worktree info - we'll run git commands from there if it exists
    worktree_info = get_worktree_info(task_id, project_id)
    cwd = str(worktree_info.path) if worktree_info else None

    # Check if subtask branch exists
    result = subprocess.run(
        ["git", "rev-parse", "--verify", subtask_branch],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        # No subtask branch - this is fine, work was done directly on task branch
        print(f"No subtask branch {subtask_branch} found - work done on task branch")
        return False

    # Subtask branch exists - merge it into task branch
    # We need to be on the task branch to merge
    current_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if current_branch.stdout.strip() != task_branch:
        try:
            subprocess.run(
                ["git", "checkout", task_branch],
                check=True,
                capture_output=True,
                text=True,
                cwd=cwd,
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
            cwd=cwd,
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
            cwd=cwd,
        )
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to delete {subtask_branch}: {e.stderr}", file=sys.stderr)

    print(f"Merged subtask branch {subtask_branch} into {task_branch}")
    return True


def merge_task_branch(task_id: str, project_id: str | None = None) -> bool:
    """Merge task branch to base branch and clean up.

    Correct order of operations (verified with git documentation):
    1. Ensure we're on base branch (main/master) in main repo
    2. Merge task branch (works even while worktree exists!)
    3. Remove worktree AFTER merge succeeds
    4. Delete task branch AFTER worktree is removed

    Args:
        task_id: Task identifier
        project_id: Project identifier for per-project worktree paths

    Returns:
        True on success

    Raises:
        SystemExit: On merge failure
    """
    from .worktree import get_worktree_info, remove_worktree

    # Load project_id and base_branch from metadata
    meta = load_snapshot_meta(task_id)
    if meta:
        project_id = project_id or meta.project_id
        base_branch = meta.base_branch
    else:
        base_branch = "main"

    task_branch = f"{task_id}/main"

    # Step 1: Ensure we're on base branch
    # Check current branch first
    current = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    current_branch = current.stdout.strip() if current.returncode == 0 else ""

    if current_branch != base_branch:
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

    # Step 2: Merge task branch (worktree can still exist - this is allowed!)
    try:
        subprocess.run(
            ["git", "merge", "--no-ff", task_branch, "-m", f"Merge task {task_id}"],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"Merged {task_branch} into {base_branch}")
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to merge {task_branch}: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    # Step 3: Remove worktree AFTER merge succeeds
    worktree_info = get_worktree_info(task_id, project_id)
    if worktree_info:
        print(f"Removing worktree: {worktree_info.path}")
        remove_worktree(task_id, delete_branch=False, project_id=project_id)

    # Step 4: Delete task branch AFTER worktree is removed
    try:
        subprocess.run(
            ["git", "branch", "-d", task_branch],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"Deleted branch {task_branch}")
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
    from .checkpoint_metadata import get_current_branch

    branch_name = f"{task_id}/{subtask_id}"
    task_branch = f"{task_id}/main"

    # Make sure we're not on the branch we're deleting
    current = get_current_branch()
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
    # Load base branch from metadata
    meta = load_snapshot_meta(task_id)
    base_branch = meta.base_branch if meta else "main"

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
        # Strip branch prefixes: * (current), + (worktree), space
        branches = [b.strip().lstrip("*+ ") for b in result.stdout.splitlines() if b.strip()]

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
