"""Worktree operation helpers."""

from __future__ import annotations

from pathlib import Path

from .worktree_git import WorktreeError, run_git


def get_project_cwd(project_id: str | None) -> Path | None:
    """Get working directory for a project.

    Args:
        project_id: Project identifier.

    Returns:
        Path to project root, or None if not found.
    """
    if not project_id:
        return None

    from app.storage.projects import get_project_root_path

    root_path = get_project_root_path(project_id)
    return Path(root_path) if root_path else None


def verify_base_branch(base_branch: str, repo_root: Path) -> None:
    """Verify that base branch exists.

    Args:
        base_branch: Branch name to verify.
        repo_root: Repository root path.

    Raises:
        WorktreeError: If base branch does not exist.
    """
    try:
        run_git(["rev-parse", "--verify", base_branch], cwd=repo_root)
    except WorktreeError as e:
        raise WorktreeError(f"Base branch '{base_branch}' does not exist") from e


def create_worktree_branch(
    worktree_path: Path, branch_name: str, base_branch: str, repo_root: Path, task_id: str
) -> None:
    """Create worktree with new branch.

    Args:
        worktree_path: Path for the worktree.
        branch_name: Name of the branch to create.
        base_branch: Branch to base the worktree on.
        repo_root: Repository root path.
        task_id: Task identifier for error messages.

    Raises:
        WorktreeError: If worktree creation fails.
    """
    try:
        run_git(
            ["worktree", "add", str(worktree_path), "-b", branch_name, base_branch],
            cwd=repo_root,
        )
    except WorktreeError as e:
        # Branch might already exist, try without -b
        if "already exists" in str(e):
            try:
                run_git(
                    ["worktree", "add", str(worktree_path), branch_name],
                    cwd=repo_root,
                )
            except WorktreeError as err:
                raise WorktreeError(f"Failed to create worktree for task '{task_id}': {e}") from err
        else:
            raise


def get_worktree_branch(worktree_path: Path) -> str | None:
    """Get the current branch of a worktree.

    Args:
        worktree_path: Path to the worktree.

    Returns:
        Branch name, or None if not found.
    """
    try:
        result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree_path, check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (WorktreeError, OSError):
        return None


def detect_base_branch(worktree_path: Path) -> str:
    """Detect the base branch for a worktree.

    Args:
        worktree_path: Path to the worktree.

    Returns:
        Base branch name (defaults to 'main').
    """
    try:
        for candidate in ["main", "master", "develop"]:
            result = run_git(
                ["rev-parse", "--verify", f"origin/{candidate}"],
                cwd=worktree_path,
                check=False,
            )
            if result.returncode == 0:
                return candidate
    except (WorktreeError, OSError):
        pass
    return "main"
