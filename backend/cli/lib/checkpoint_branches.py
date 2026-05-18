"""Git branch operations for checkpoint system.

Reads and deletes task-family branches left over from the legacy
branch-checkpoint era. Work commits direct to main; parallel coordination is
file-level via `st lease`. No branch creation or merge code lives here.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys

from app.utils.git_base import normalize_base_branch

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


def _clean_branch_lines(output: str) -> list[str]:
    return [line.strip().lstrip("*+ ") for line in output.splitlines() if line.strip()]


def _branch_exists(branch: str, cwd: str | None = None) -> bool:
    return _run_git(["git", "rev-parse", "--verify", branch], cwd=cwd, check=False).returncode == 0


def _classify_branch(branch: str) -> dict[str, str]:
    """Classify a task-family branch as task or subtask type."""
    task_id = branch.split("/", 1)[0]
    if branch == task_id:
        return {"branch": branch, "subtask_id": "", "type": "task"}
    suffix = branch.split("/")[-1] if "/" in branch else ""
    if suffix == "main":
        return {"branch": branch, "subtask_id": "", "type": "task"}
    return {"branch": branch, "subtask_id": suffix, "type": "subtask"}


def get_task_branches(task_id: str, project_id: str | None = None) -> list[dict[str, str]]:
    """List task-family branches for a checkpoint in the project's canonical repo."""
    branches: list[dict[str, str]] = []
    cwd = _get_repo_cwd(project_id)
    seen: set[str] = set()
    for pattern in (task_id, f"{task_id}/*"):
        try:
            result = _run_git(["git", "branch", "--list", pattern], cwd=cwd)
        except subprocess.CalledProcessError:
            continue

        for branch in _clean_branch_lines(result.stdout):
            if branch and branch not in seen:
                seen.add(branch)
                branches.append(_classify_branch(branch))
    return branches


def resolve_task_branch(task_id: str, project_id: str | None = None) -> str:
    """Return the concrete task branch name for a task id."""
    cwd = _get_repo_cwd(project_id)
    committed_task_branch = f"task/{task_id}"
    if _branch_exists(committed_task_branch, cwd):
        return committed_task_branch
    preferred = f"{task_id}/main"
    if _branch_exists(preferred, cwd):
        return preferred
    if _branch_exists(task_id, cwd):
        return task_id
    task_branch = next(
        (branch["branch"] for branch in get_task_branches(task_id, project_id=project_id) if branch.get("type") == "task"),
        None,
    )
    return task_branch or preferred


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


def get_remote_task_branches(task_id: str, project_id: str | None = None, remote: str = "origin") -> list[str]:
    """Return remote task-family branches for a task."""
    repo_cwd = _get_repo_cwd(project_id)
    result = _run_git(
        ["git", "for-each-ref", "--format=%(refname:short)", f"refs/remotes/{remote}/{task_id}"],
        repo_cwd,
        check=False,
    )
    if result.returncode != 0:
        return []
    prefix = f"{remote}/"
    return [
        ref.removeprefix(prefix)
        for ref in (line.strip() for line in result.stdout.splitlines())
        if ref.startswith(prefix) and ref.removeprefix(prefix)
    ]


def _delete_remote_task_branches(task_id: str, repo_cwd: str | None, remote: str = "origin") -> int:
    """Delete pushed task-family branches for abandoned work."""
    result = _run_git(
        ["git", "for-each-ref", "--format=%(refname:short)", f"refs/remotes/{remote}/{task_id}"],
        repo_cwd,
        check=False,
    )
    if result.returncode != 0:
        return 0
    prefix = f"{remote}/"
    remote_branches = [
        ref.removeprefix(prefix)
        for ref in (line.strip() for line in result.stdout.splitlines())
        if ref.startswith(prefix) and ref.removeprefix(prefix)
    ]
    deleted = 0
    for branch in remote_branches:
        result = _run_git(["git", "push", remote, "--delete", branch], repo_cwd, check=False)
        detail = f"{result.stdout}\n{result.stderr}"
        if result.returncode == 0 or "remote ref does not exist" in detail:
            deleted += 1
            print(f"Deleted remote branch: {remote}/{branch}")
        else:
            print(f"Warning: Failed to delete remote branch {remote}/{branch}: {detail.strip()}", file=sys.stderr)
    if deleted:
        _run_git(["git", "fetch", remote, "--prune"], repo_cwd, check=False)
    return deleted


def delete_task_branches(task_id: str, project_id: str | None = None) -> bool:
    """Delete task branch and all subtask branches (used when abandoning task)."""
    meta = load_snapshot_meta(task_id)
    resolved_project_id = project_id or (meta.project_id if meta else None)
    repo_cwd = _get_repo_cwd(resolved_project_id)
    base_branch = normalize_base_branch(meta.base_branch if meta else "main", repo_cwd)

    with contextlib.suppress(subprocess.CalledProcessError):
        _run_git(["git", "checkout", base_branch], repo_cwd)
        _run_git(["git", "checkout", "."], repo_cwd)

    try:
        result = _run_git(["git", "branch", "--list", f"{task_id}*"], repo_cwd)
        for branch in _clean_branch_lines(result.stdout):
            with contextlib.suppress(subprocess.CalledProcessError):
                _run_git(["git", "branch", "-D", branch], repo_cwd)
                print(f"Deleted branch: {branch}")
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to list branches: {e.stderr}", file=sys.stderr)

    _delete_remote_task_branches(task_id, repo_cwd)
    return True
