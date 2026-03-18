"""Git branch operations."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ...logging_config import get_logger

logger = get_logger(__name__)


def slugify(text: str, max_length: int = 40) -> str:
    """Convert text to a git-safe slug.

    Args:
        text: Text to slugify
        max_length: Maximum length of the slug

    Returns:
        Lowercase hyphenated slug
    """
    # Convert to lowercase
    slug = text.lower()
    # Replace spaces and underscores with hyphens
    slug = re.sub(r"[\s_]+", "-", slug)
    # Remove any characters that aren't alphanumeric or hyphens
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    # Remove multiple consecutive hyphens
    slug = re.sub(r"-+", "-", slug)
    # Remove leading/trailing hyphens
    slug = slug.strip("-")
    # Truncate to max length
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug


def create_task_branch(
    task_id: str,
    feature_title: str,
    project_path: str | Path,
) -> str:
    """Create a git branch for a task.

    Creates a new branch from the current HEAD with the naming convention:
    task/{task_id}-{slug}

    Args:
        task_id: The task ID (e.g., task-abc123)
        feature_title: The feature title to include in the branch name
        project_path: Path to the git repository

    Returns:
        The created branch name.

    Raises:
        RuntimeError: If git operations fail
    """
    project_path = Path(project_path)

    # Verify it's a git repository
    if not (project_path / ".git").exists():
        logger.error("not_git_repo", path=str(project_path))
        raise RuntimeError(f"Not a git repository: {project_path}")

    # Generate branch name
    slug = slugify(feature_title)
    # Extract just the ID part (e.g., abc123 from task-abc123)
    short_id = task_id.replace("task-", "")
    branch_name = f"task/{short_id}-{slug}"

    try:
        # Check if branch already exists
        result = subprocess.run(
            ["git", "branch", "--list", branch_name],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            logger.info("branch_exists", branch=branch_name)
            # Branch exists, just return it
            return branch_name

        # Create the branch from HEAD
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=project_path,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error(
                "branch_creation_failed",
                branch=branch_name,
                error=result.stderr,
            )
            raise RuntimeError(f"Failed to create branch: {result.stderr}")

        logger.info("branch_created", branch=branch_name)

        # Update task with branch name
        from ...storage import tasks as task_store

        task_store.update_task(task_id, branch_name=branch_name)

        return branch_name

    except subprocess.SubprocessError as e:
        logger.error("git_error", error=str(e))
        raise RuntimeError(f"Git error: {e}") from e


def get_current_branch(project_path: str | Path) -> str:
    """Get the current git branch name.

    Args:
        project_path: Path to the git repository

    Returns:
        Current branch name
    """
    project_path = Path(project_path)

    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to get current branch: {result.stderr}")

    return result.stdout.strip()


def checkout_branch(
    branch_name: str,
    project_path: str | Path,
) -> bool:
    """Checkout an existing branch.

    Args:
        branch_name: Name of the branch to checkout
        project_path: Path to the git repository

    Returns:
        True if successful
    """
    project_path = Path(project_path)

    result = subprocess.run(
        ["git", "checkout", branch_name],
        cwd=project_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("checkout_failed", branch=branch_name, error=result.stderr)
        raise RuntimeError(f"Failed to checkout branch: {result.stderr}")

    logger.info("branch_checked_out", branch=branch_name)
    return True
