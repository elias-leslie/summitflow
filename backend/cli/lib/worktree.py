"""Worktree management for CLI task isolation.

Provides git worktree operations for st claim workflow.
Each claimed task gets an isolated worktree at:
    ~/.local/share/st/worktrees/<project-id>/<task-id>/

With the existing branch naming:
    <task-id>/main
"""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorktreeError(Exception):
    """Error during worktree operations."""

    pass


@dataclass
class WorktreeInfo:
    """Information about a task's worktree."""

    path: Path
    branch: str
    task_id: str
    base_branch: str
    is_active: bool = True
    project_id: str | None = None


def get_worktrees_base_dir(project_id: str | None = None) -> Path:
    """Returns worktrees directory for a project.

    Path format: ~/.local/share/st/worktrees/<project-id>/
    If project_id is None, returns the base worktrees directory.

    Creates the directory if it doesn't exist.

    Args:
        project_id: Project identifier. If None, returns base worktrees dir.

    Returns:
        Path to the worktrees directory (project-specific if project_id given).
    """
    base_dir = Path.home() / ".local" / "share" / "st" / "worktrees"
    if project_id:
        base_dir = base_dir / project_id
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_worktree_path(task_id: str, project_id: str | None = None) -> Path:
    """Returns the path for a specific task's worktree.

    Args:
        task_id: The task identifier.
        project_id: Project identifier for per-project paths.

    Returns:
        Path to the worktree directory.
    """
    sanitized = _sanitize_task_id(task_id)
    return get_worktrees_base_dir(project_id) / sanitized


def _sanitize_task_id(task_id: str) -> str:
    """Sanitize task ID for safe use in file paths.

    Args:
        task_id: The raw task identifier.

    Returns:
        Sanitized task ID safe for paths.
    """
    # Replace any characters that aren't alphanumeric, dash, or underscore
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", task_id)
    # Remove leading/trailing underscores and collapse multiple underscores
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    # Ensure we have something
    if not sanitized:
        sanitized = "task"
    return sanitized


def _run_git(
    args: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a git command.

    Args:
        args: Git command arguments (without 'git' prefix).
        cwd: Working directory for the command.
        check: Whether to raise on non-zero exit code.

    Returns:
        CompletedProcess with command results.

    Raises:
        WorktreeError: If command fails and check is True.
    """
    cmd = ["git", *args]
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=check,
        )
        return result
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip() if e.stderr else str(e)
        raise WorktreeError(f"Git command failed: {' '.join(cmd)}\n{stderr}") from e


def _get_repo_root(cwd: Path | None = None) -> Path:
    """Get the root of the current git repository.

    Args:
        cwd: Working directory to start from.

    Returns:
        Path to the repository root.

    Raises:
        WorktreeError: If not in a git repository.
    """
    result = _run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
    return Path(result.stdout.strip())


def _get_branch_name(task_id: str) -> str:
    """Get the branch name for a task.

    Args:
        task_id: The task identifier.

    Returns:
        Branch name in format: <task-id>/main
    """
    return f"{task_id}/main"


def _symlink_gitignored_deps(repo_root: Path, worktree_path: Path) -> None:
    """Symlink gitignored dependency directories from main repo into worktree.

    git worktree add doesn't include gitignored dirs (node_modules, .venv).
    Without these, tools like `dt --check` fail when they detect frontend/
    exists but node_modules/ is missing.
    """
    symlink_pairs = [
        ("frontend/node_modules", "frontend"),
    ]
    created_symlinks: list[str] = []
    for dep_rel, parent_rel in symlink_pairs:
        main_dep = repo_root / dep_rel
        wt_parent = worktree_path / parent_rel
        if main_dep.exists() and wt_parent.exists():
            wt_dep = worktree_path / dep_rel
            if not wt_dep.exists():
                wt_dep.symlink_to(main_dep)
                created_symlinks.append(dep_rel)

    if created_symlinks:
        git_dir = worktree_path / ".git"
        if git_dir.is_file():
            real_git = Path(git_dir.read_text().strip().removeprefix("gitdir: "))
            exclude_file = real_git / "info" / "exclude"
        else:
            exclude_file = git_dir / "info" / "exclude"
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_file.read_text() if exclude_file.exists() else ""
        with open(exclude_file, "a") as f:
            for dep in created_symlinks:
                if dep not in existing:
                    f.write(f"{dep}\n")


def create_worktree(
    task_id: str, base_branch: str = "main", project_id: str | None = None
) -> WorktreeInfo:
    """Create a worktree for a task.

    Args:
        task_id: The task identifier.
        base_branch: The branch to base the worktree on.
        project_id: Project identifier for per-project paths.

    Returns:
        WorktreeInfo with details about the created worktree.

    Raises:
        WorktreeError: If worktree creation fails.
    """
    worktree_path = get_worktree_path(task_id, project_id)
    branch_name = _get_branch_name(task_id)

    # Check if worktree already exists
    if worktree_path.exists():
        existing_info = get_worktree_info(task_id, project_id)
        if existing_info:
            return existing_info
        # Directory exists but not a valid worktree, clean it up
        shutil.rmtree(worktree_path)

    # Get repo root for the target project (not CWD which may be wrong in Celery)
    project_cwd: Path | None = None
    if project_id:
        from app.storage.projects import get_project_root_path

        root_path = get_project_root_path(project_id)
        if root_path:
            project_cwd = Path(root_path)
    repo_root = _get_repo_root(cwd=project_cwd)

    # Ensure base branch exists and is up to date
    try:
        _run_git(["rev-parse", "--verify", base_branch], cwd=repo_root)
    except WorktreeError as e:
        raise WorktreeError(f"Base branch '{base_branch}' does not exist") from e

    # Create the worktree with a new branch
    try:
        _run_git(
            ["worktree", "add", str(worktree_path), "-b", branch_name, base_branch],
            cwd=repo_root,
        )
    except WorktreeError as e:
        # Branch might already exist, try without -b
        if "already exists" in str(e):
            try:
                _run_git(
                    ["worktree", "add", str(worktree_path), branch_name],
                    cwd=repo_root,
                )
            except WorktreeError as err:
                raise WorktreeError(f"Failed to create worktree for task '{task_id}': {e}") from err
        else:
            raise

    _symlink_gitignored_deps(repo_root, worktree_path)

    return WorktreeInfo(
        path=worktree_path,
        branch=branch_name,
        task_id=task_id,
        base_branch=base_branch,
        is_active=True,
        project_id=project_id,
    )


def get_worktree_info(task_id: str, project_id: str | None = None) -> WorktreeInfo | None:
    """Get information about an existing worktree.

    Args:
        task_id: The task identifier.
        project_id: Project identifier for per-project paths.

    Returns:
        WorktreeInfo if worktree exists, None otherwise.
    """
    worktree_path = get_worktree_path(task_id, project_id)

    if not worktree_path.exists():
        return None

    # Verify it's a valid git worktree
    git_dir = worktree_path / ".git"
    if not git_dir.exists():
        return None

    # Get current branch
    try:
        result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree_path, check=False)
        if result.returncode != 0:
            return None
        branch = result.stdout.strip()
    except (WorktreeError, OSError):
        return None

    # Try to determine base branch from reflog or merge-base
    base_branch = "main"  # Default assumption
    try:
        # Check common base branches
        for candidate in ["main", "master", "develop"]:
            result = _run_git(
                ["rev-parse", "--verify", f"origin/{candidate}"],
                cwd=worktree_path,
                check=False,
            )
            if result.returncode == 0:
                base_branch = candidate
                break
    except (WorktreeError, OSError):
        pass

    return WorktreeInfo(
        path=worktree_path,
        branch=branch,
        task_id=task_id,
        base_branch=base_branch,
        is_active=True,
        project_id=project_id,
    )


def remove_worktree(
    task_id: str, delete_branch: bool = True, project_id: str | None = None
) -> bool:
    """Remove a task's worktree and optionally its branch.

    Args:
        task_id: The task identifier.
        delete_branch: Whether to also delete the associated branch.
        project_id: Project identifier for per-project paths.

    Returns:
        True if worktree was removed, False if it didn't exist.

    Raises:
        WorktreeError: If removal fails.
    """
    worktree_path = get_worktree_path(task_id, project_id)
    branch_name = _get_branch_name(task_id)

    if not worktree_path.exists():
        return False

    # Get repo root before removing worktree
    try:
        repo_root = _get_repo_root()
    except WorktreeError:
        # Try to find repo root from worktree itself
        try:
            repo_root = _get_repo_root(worktree_path)
        except WorktreeError:
            # Can't find repo, just remove the directory
            shutil.rmtree(worktree_path)
            return True

    # Remove the worktree using git
    try:
        _run_git(["worktree", "remove", str(worktree_path), "--force"], cwd=repo_root)
    except WorktreeError:
        # Force removal if git worktree remove fails
        try:
            shutil.rmtree(worktree_path)
            # Prune stale worktree entries
            _run_git(["worktree", "prune"], cwd=repo_root, check=False)
        except OSError as e:
            raise WorktreeError(f"Failed to remove worktree directory: {e}") from e

    # Delete the branch if requested (best-effort)
    if delete_branch:
        with contextlib.suppress(WorktreeError):
            _run_git(["branch", "-D", branch_name], cwd=repo_root, check=False)

    return True


def get_active_worktrees(project_id: str | None = None) -> list[WorktreeInfo]:
    """List all active worktrees.

    If project_id is provided, lists worktrees for that project.
    If project_id is None, lists worktrees across all projects.

    Args:
        project_id: Project identifier. If None, lists all worktrees.

    Returns:
        List of WorktreeInfo for each active worktree.
    """
    worktrees: list[WorktreeInfo] = []

    if project_id:
        # List worktrees for specific project
        base_dir = get_worktrees_base_dir(project_id)
        if not base_dir.exists():
            return worktrees

        for entry in base_dir.iterdir():
            if entry.is_dir():
                task_id = entry.name
                info = get_worktree_info(task_id, project_id)
                if info:
                    worktrees.append(info)
    else:
        # List worktrees across all projects
        base_dir = get_worktrees_base_dir()
        if not base_dir.exists():
            return worktrees

        for project_entry in base_dir.iterdir():
            if project_entry.is_dir():
                proj_id = project_entry.name
                for task_entry in project_entry.iterdir():
                    if task_entry.is_dir():
                        task_id = task_entry.name
                        info = get_worktree_info(task_id, proj_id)
                        if info:
                            worktrees.append(info)

    return worktrees


def get_current_branch(cwd: Path | None = None) -> str | None:
    """Get the current branch name.

    Args:
        cwd: Working directory to check. If None, uses current directory.

    Returns:
        Current branch name, or None if not in a git repo or detached HEAD.
    """
    try:
        result = _run_git(["symbolic-ref", "--short", "HEAD"], cwd=cwd, check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (WorktreeError, OSError):
        return None


def check_worktree_safety(
    cwd: Path | None = None, project_id: str | None = None
) -> tuple[bool, str | None]:
    """Check if it's safe to commit on main.

    Detects when someone is about to commit on main/master while having
    active worktrees, which usually indicates they should be working in
    a worktree instead.

    Args:
        cwd: Working directory to check. If None, uses current directory.
        project_id: Project identifier for per-project worktree checks.

    Returns:
        Tuple of (is_safe, warning_message).
        - is_safe: True if safe to proceed, False if suspicious state detected.
        - warning_message: Detailed warning if not safe, None otherwise.
    """
    # Get current branch
    current_branch = get_current_branch(cwd)
    if current_branch is None:
        # Not in a git repo or detached HEAD - allow
        return (True, None)

    # Only check for main/master branches
    if current_branch not in ("main", "master"):
        return (True, None)

    # Check for active worktrees
    active_worktrees = get_active_worktrees(project_id)
    if not active_worktrees:
        # No active worktrees - still on main, but no task isolation in use
        return (True, None)

    # Suspicious state: on main/master with active worktrees
    lines = [
        f"WARNING: You are on '{current_branch}' with {len(active_worktrees)} active worktree(s).",
        "",
        "Active worktrees:",
    ]

    for wt in active_worktrees:
        lines.append(f"  - Task: {wt.task_id}")
        lines.append(f"    Branch: {wt.branch}")
        lines.append(f"    Path: {wt.path}")

    lines.extend(
        [
            "",
            "This usually means you should be working in one of these worktrees",
            "instead of committing directly to the main branch.",
            "",
            "Options:",
            "  1. Switch to a worktree: cd <worktree-path>",
            "  2. Create a new task: sf task create <task-name>",
            "  3. Bypass this check: git commit --no-verify",
        ]
    )

    return (False, "\n".join(lines))
