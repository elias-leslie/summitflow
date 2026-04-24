"""Git branch operations for checkpoint system.

Handles creation, merging, and deletion of task and subtask branches.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import sys

from .checkpoint_metadata import load_snapshot_meta

_CONFLICT_RE = re.compile(r"CONFLICT \([^)]*\): Merge conflict in (.+)")


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


def _abort_merge(cwd: str | None = None) -> None:
    """Abort an in-progress merge to restore clean working tree state."""
    _run_git(["git", "merge", "--abort"], cwd=cwd, check=False)


def _merge_failure_output(error: subprocess.CalledProcessError) -> str:
    parts = [
        str(part).strip()
        for part in (error.stderr, error.stdout)
        if str(part or "").strip()
    ]
    return "\n".join(parts)


def _conflict_paths_from_output(output: str) -> list[str]:
    paths: list[str] = []
    for line in output.splitlines():
        match = _CONFLICT_RE.search(line)
        if match:
            paths.append(match.group(1).strip())
    return list(dict.fromkeys(paths))


def _conflict_paths_from_index(cwd: str | None = None) -> list[str]:
    result = _run_git(["git", "diff", "--name-only", "--diff-filter=U"], cwd=cwd, check=False)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _format_merge_failure(
    branch: str,
    error: subprocess.CalledProcessError,
    cwd: str | None,
    recovery: str,
) -> str:
    output = _merge_failure_output(error)
    detail = output or f"git exited {error.returncode}"
    conflicts = _conflict_paths_from_output(output) or _conflict_paths_from_index(cwd)
    lines = [f"Error: Failed to merge {branch}: {detail}"]
    if conflicts:
        shown = ", ".join(conflicts[:10])
        lines.append(f"Conflicts: {shown}")
        if len(conflicts) > 10:
            lines.append(f"Conflicts omitted: {len(conflicts) - 10}")
    lines.append(f"Recovery: {recovery}")
    return "\n".join(lines)


def _get_current_branch(cwd: str | None = None) -> str:
    """Get current branch name."""
    result = _run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _branch_exists(branch: str, cwd: str | None = None) -> bool:
    """Check if branch exists."""
    result = _run_git(["git", "rev-parse", "--verify", branch], cwd=cwd, check=False)
    return result.returncode == 0


def _classify_branch(branch: str) -> dict[str, str]:
    """Classify a task-family branch as task or subtask type."""
    suffix = branch.split("/")[-1] if "/" in branch else ""
    if suffix == "main":
        return {"branch": branch, "subtask_id": "", "type": "task"}
    return {"branch": branch, "subtask_id": suffix, "type": "subtask"}


def get_task_branches(task_id: str, project_id: str | None = None) -> list[dict[str, str]]:
    """List task-family branches for a checkpoint in the project's canonical repo."""
    branches: list[dict[str, str]] = []
    cwd = _get_repo_cwd(project_id)
    try:
        result = _run_git(["git", "branch", "--list", f"{task_id}/*"], cwd=cwd)
    except subprocess.CalledProcessError:
        return branches

    for line in result.stdout.splitlines():
        branch = line.strip().lstrip("* ")
        if branch:
            branches.append(_classify_branch(branch))
    return branches


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
    """Merge subtask branch into the task branch in the shared checkout."""
    subtask_branch = f"{task_id}/{subtask_id}"
    task_branch = f"{task_id}/main"
    cwd = _get_repo_cwd(project_id)

    if not _branch_exists(subtask_branch, cwd):
        print(f"No subtask branch {subtask_branch} found - work done on task branch")
        return False

    if _get_current_branch(cwd) != task_branch:
        _checkout_branch(task_branch, cwd)

    try:
        _run_git(["git", "merge", "--no-ff", subtask_branch, "-m", f"Merge subtask {subtask_id}"], cwd)
    except subprocess.CalledProcessError as e:
        message = _format_merge_failure(
            subtask_branch,
            e,
            cwd,
            f"resolve conflicts, then rerun st done {subtask_id} -t {task_id}",
        )
        _abort_merge(cwd)
        print(message, file=sys.stderr)
        sys.exit(1)

    with contextlib.suppress(subprocess.CalledProcessError):
        _run_git(["git", "branch", "-d", subtask_branch], cwd)

    print(f"Merged subtask branch {subtask_branch} into {task_branch}")
    return True


def merge_task_branch(task_id: str, project_id: str | None = None) -> bool:
    """Merge task branch to base branch, then delete the task branch."""
    from app.storage import tasks as task_store

    task = task_store.get_task(task_id)
    if task and task.get("status") in ("completed", "cancelled"):
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
        message = _format_merge_failure(
            task_branch,
            e,
            repo_cwd,
            f"st git resolve-conflict {task_id}",
        )
        _abort_merge(repo_cwd)
        print(message, file=sys.stderr)
        sys.exit(1)

    with contextlib.suppress(subprocess.CalledProcessError):
        _run_git(["git", "branch", "-d", task_branch], repo_cwd)
        print(f"Deleted branch {task_branch}")

    with contextlib.suppress(subprocess.CalledProcessError):
        _run_git(["git", "push"], repo_cwd)

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
