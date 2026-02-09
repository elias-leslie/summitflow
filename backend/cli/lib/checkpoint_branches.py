"""Git branch operations for checkpoint system.

Handles creation, merging, and deletion of task and subtask branches.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys

from .checkpoint_metadata import load_snapshot_meta


def _run_git(args: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git command with standard options."""
    return subprocess.run(args, check=check, capture_output=True, text=True, cwd=cwd)


def _get_repo_cwd(project_id: str | None) -> str | None:
    """Get repository working directory for project."""
    if not project_id:
        return None
    from app.storage.projects import get_project_root_path
    return get_project_root_path(project_id)


def _checkout_branch(branch: str, cwd: str | None = None) -> None:
    """Checkout branch with error handling."""
    try:
        _run_git(["git", "checkout", branch], cwd=cwd)
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to checkout {branch}: {e.stderr}", file=sys.stderr)
        sys.exit(1)


def _get_current_branch(cwd: str | None = None) -> str:
    """Get current branch name."""
    result = _run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _branch_exists(branch: str, cwd: str | None = None) -> bool:
    """Check if branch exists."""
    result = _run_git(["git", "rev-parse", "--verify", branch], cwd=cwd, check=False)
    return result.returncode == 0


def create_subtask_branch(task_id: str, subtask_id: str) -> str:
    """Create git branch for subtask. Format: {task_id}/{subtask_id}"""
    branch_name = f"{task_id}/{subtask_id}"
    try:
        _run_git(["git", "checkout", "-b", branch_name])
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to create branch {branch_name}: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    return branch_name


def merge_subtask_branch(task_id: str, subtask_id: str, project_id: str | None = None) -> bool:
    """Merge subtask branch to task branch. Worktree stays alive until task completes."""
    from .worktree import get_worktree_info

    subtask_branch = f"{task_id}/{subtask_id}"
    task_branch = f"{task_id}/main"
    worktree_info = get_worktree_info(task_id, project_id)
    cwd = str(worktree_info.path) if worktree_info else None

    if not _branch_exists(subtask_branch, cwd):
        print(f"No subtask branch {subtask_branch} found - work done on task branch")
        return False

    if _get_current_branch(cwd) != task_branch:
        _checkout_branch(task_branch, cwd)

    try:
        _run_git(["git", "merge", "--no-ff", subtask_branch, "-m", f"Merge subtask {subtask_id}"], cwd)
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to merge {subtask_branch}: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    with contextlib.suppress(subprocess.CalledProcessError):
        _run_git(["git", "branch", "-d", subtask_branch], cwd)

    print(f"Merged subtask branch {subtask_branch} into {task_branch}")
    return True


def merge_task_branch(task_id: str, project_id: str | None = None) -> bool:
    """Merge task branch to base branch. Order: checkout base, merge, remove worktree, delete branch."""
    from app.storage import tasks as task_store

    from .worktree import get_worktree_info, remove_worktree

    task = task_store.get_task(task_id)
    if task and task.get("status") in ("completed", "abandoned", "cancelled"):
        print(f"Error: Cannot merge - task {task_id} is already {task['status']}", file=sys.stderr)
        sys.exit(1)

    meta = load_snapshot_meta(task_id)
    project_id = project_id or (meta.project_id if meta else None)
    base_branch = meta.base_branch if meta else "main"
    repo_cwd = _get_repo_cwd(project_id)
    task_branch = f"{task_id}/main"

    if _get_current_branch(repo_cwd) != base_branch:
        _checkout_branch(base_branch, repo_cwd)

    try:
        _run_git(["git", "merge", "--no-ff", task_branch, "-m", f"Merge task {task_id}"], repo_cwd)
        print(f"Merged {task_branch} into {base_branch}")
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to merge {task_branch}: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    worktree_info = get_worktree_info(task_id, project_id)
    if worktree_info:
        print(f"Removing worktree: {worktree_info.path}")
        remove_worktree(task_id, delete_branch=False, project_id=project_id)

    with contextlib.suppress(subprocess.CalledProcessError):
        _run_git(["git", "branch", "-d", task_branch], repo_cwd)
        print(f"Deleted branch {task_branch}")

    return True


def delete_subtask_branch(task_id: str, subtask_id: str) -> bool:
    """Delete subtask branch without merging (used when abandoning)."""
    from .checkpoint_metadata import get_current_branch

    branch_name = f"{task_id}/{subtask_id}"
    if get_current_branch() == branch_name:
        with contextlib.suppress(subprocess.CalledProcessError):
            _run_git(["git", "checkout", f"{task_id}/main"])

    try:
        _run_git(["git", "branch", "-D", branch_name])
        return True
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to delete {branch_name}: {e.stderr}", file=sys.stderr)
        return False


def delete_task_branches(task_id: str) -> bool:
    """Delete task branch and all subtask branches (used when abandoning task)."""
    meta = load_snapshot_meta(task_id)
    base_branch = meta.base_branch if meta else "main"

    with contextlib.suppress(subprocess.CalledProcessError):
        _run_git(["git", "checkout", base_branch])
        _run_git(["git", "checkout", "."])

    try:
        result = _run_git(["git", "branch", "--list", f"{task_id}*"])
        branches = [b.strip().lstrip("*+ ") for b in result.stdout.splitlines() if b.strip()]
        for branch in branches:
            with contextlib.suppress(subprocess.CalledProcessError):
                _run_git(["git", "branch", "-D", branch])
                print(f"Deleted branch: {branch}")
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to list branches: {e.stderr}", file=sys.stderr)

    return True
