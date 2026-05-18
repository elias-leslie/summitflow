"""Git branch operations for checkpoint system.

Handles creation, merging, and deletion of task and subtask branches.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import sys
from datetime import UTC, datetime

from app.utils.git_base import current_branch, normalize_base_branch

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


def _clean_branch_lines(output: str) -> list[str]:
    return [line.strip().lstrip("*+ ") for line in output.splitlines() if line.strip()]


def _abort_merge(cwd: str | None = None) -> None:
    """Abort an in-progress merge to restore clean working tree state."""
    _run_git(["git", "merge", "--abort"], cwd=cwd, check=False)


def _get_current_branch(cwd: str | None = None) -> str:
    return current_branch(cwd) or ""


def _branch_exists(branch: str, cwd: str | None = None) -> bool:
    return _run_git(["git", "rev-parse", "--verify", branch], cwd=cwd, check=False).returncode == 0


def _merge_failure_output(error: subprocess.CalledProcessError) -> str:
    parts = [
        str(part).strip()
        for part in (error.stderr, error.stdout)
        if str(part or "").strip()
    ]
    return "\n".join(parts)


def _merge_conflict_paths(error: subprocess.CalledProcessError, cwd: str | None) -> list[str]:
    output = _merge_failure_output(error)
    paths = [match.group(1).strip() for line in output.splitlines() if (match := _CONFLICT_RE.search(line))]
    if paths:
        return list(dict.fromkeys(paths))
    result = _run_git(["git", "diff", "--name-only", "--diff-filter=U"], cwd=cwd, check=False)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _format_merge_failure(
    branch: str,
    error: subprocess.CalledProcessError,
    cwd: str | None,
    recovery: str,
    conflicts: list[str] | None = None,
) -> str:
    output = _merge_failure_output(error)
    detail = output or f"git exited {error.returncode}"
    conflicts = conflicts if conflicts is not None else _merge_conflict_paths(error, cwd)
    lines = [f"Error: Failed to merge {branch}: {detail}"]
    if conflicts:
        shown = ", ".join(conflicts[:10])
        lines.append(f"Conflicts: {shown}")
        if len(conflicts) > 10:
            lines.append(f"Conflicts omitted: {len(conflicts) - 10}")
    lines.append(f"Recovery: {recovery}")
    return "\n".join(lines)


def _record_task_merge_conflict(
    task_id: str,
    task_branch: str,
    base_branch: str,
    conflicts: list[str],
    error_output: str,
) -> None:
    if not conflicts:
        return
    try:
        from app.storage import log_task_event
        from app.storage.tasks.status import update_task_status
        from app.storage.tasks.update import update_task_fields

        update_task_fields(
            task_id,
            conflict_info={
                "conflicting_files": conflicts,
                "task_branch": task_branch,
                "base_branch": base_branch,
                "detected_at": datetime.now(UTC).isoformat(),
                "error_output": error_output[:500],
            },
        )
        update_task_status(
            task_id,
            "failed",
            error_message=f"Merge conflict in {len(conflicts)} file(s)",
            validate_transition=False,
        )
        log_task_event(
            task_id,
            f"Merge conflict detected in {len(conflicts)} file(s): {', '.join(conflicts[:5])}",
        )
    except Exception as exc:
        print(f"Warning: Failed to record merge conflict metadata: {exc}", file=sys.stderr)


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


def create_subtask_branch(task_id: str, subtask_id: str) -> str:
    """No-op. Subtask work commits direct to main; parallel coordination via st lease."""
    return f"{task_id}/{subtask_id}"


def merge_subtask_branch(task_id: str, subtask_id: str, project_id: str | None = None) -> bool:
    """No-op. Subtask work is committed direct to main via st commit; nothing to merge.

    Returns False to signal "no merge happened" so existing callers handle it
    as the already-on-main path.
    """
    del task_id, subtask_id, project_id
    return False


def merge_task_branch(task_id: str, project_id: str | None = None) -> bool:
    """Merge legacy task branch into base, then delete it."""
    meta = load_snapshot_meta(task_id)
    resolved_project_id = project_id or (meta.project_id if meta else None)
    repo_cwd = _get_repo_cwd(resolved_project_id)
    base_branch = normalize_base_branch(meta.base_branch if meta else "main", repo_cwd)
    branch_name = resolve_task_branch(task_id, project_id=resolved_project_id)
    if not _branch_exists(branch_name, repo_cwd):
        return True
    current = _get_current_branch(repo_cwd)

    if current != base_branch:
        _checkout_branch(base_branch, repo_cwd)

    try:
        _run_git(["git", "merge", "--no-ff", branch_name, "-m", f"Merge task {task_id}"], repo_cwd)
    except subprocess.CalledProcessError as exc:
        conflicts = _merge_conflict_paths(exc, repo_cwd)
        _record_task_merge_conflict(task_id, branch_name, base_branch, conflicts, _merge_failure_output(exc))
        _abort_merge(repo_cwd)
        print(
            _format_merge_failure(
                branch_name,
                exc,
                repo_cwd,
                recovery=f"st git resolve-conflict {task_id}",
                conflicts=conflicts,
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    with contextlib.suppress(subprocess.CalledProcessError):
        _run_git(["git", "branch", "-D", branch_name], repo_cwd)
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
