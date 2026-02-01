"""Git pull request operations."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from .utils import push_branch

logger = get_logger(__name__)


def create_pull_request(
    task: dict[str, Any],
    project_path: str | Path,
    base_branch: str = "main",
) -> str | None:
    """Create a GitHub pull request for a task.

    Uses the GitHub CLI (gh) to create a PR from the task's branch.

    Args:
        task: Task dict with branch_name and feature info
        project_path: Path to the git repository
        base_branch: Target branch for PR (default: main)

    Returns:
        The PR URL if successful, None if creation failed

    Raises:
        RuntimeError: If PR creation fails
    """
    project_path = Path(project_path)

    branch_name = task.get("branch_name")
    if not branch_name:
        logger.error("no_branch_for_pr", task_id=task.get("id"))
        raise RuntimeError("Task has no branch_name, cannot create PR")

    # Build PR title
    pr_title = task.get("title", f"Task {task.get('id', '')}")

    # Build PR body
    pr_body = _build_pr_body(task)

    # Ensure branch is pushed to remote
    try:
        push_branch(branch_name, project_path)
    except RuntimeError as e:
        # Branch might already exist on remote, try to continue
        if "already exists" not in str(e).lower():
            logger.warning("push_warning", error=str(e))

    # Create PR using gh CLI
    result = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            pr_title,
            "--body",
            pr_body,
            "--base",
            base_branch,
            "--head",
            branch_name,
        ],
        cwd=project_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Check if PR already exists
        if "already exists" in result.stderr.lower():
            logger.info("pr_already_exists", branch=branch_name)
            # Try to get existing PR URL
            pr_url = _get_existing_pr_url(branch_name, project_path)
            if pr_url:
                _store_pr_url(task.get("id"), pr_url)
                return pr_url
        logger.error("pr_creation_failed", error=result.stderr)
        raise RuntimeError(f"Failed to create PR: {result.stderr}")

    # Extract PR URL from output
    pr_url = result.stdout.strip()
    logger.info("pr_created", url=pr_url)

    # Store PR URL in task
    _store_pr_url(task.get("id"), pr_url)

    return pr_url


def auto_create_pr(
    task_id: str,
    project_path: str | Path,
    title: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """Create a pull request from the task's branch.

    This is called when an agent completes task execution. It:
    1. Pushes the branch to origin
    2. Creates a PR via gh CLI
    3. Updates the task with PR URL
    4. Triggers AI review transition

    Args:
        task_id: Task ID
        project_path: Path to git repository
        title: PR title (defaults to task title)
        body: PR body (defaults to task description)

    Returns:
        Dict with pr_url and branch_name

    Raises:
        RuntimeError: If PR creation fails
    """
    project_path = Path(project_path)

    # Get task info
    from ...storage import tasks as task_store

    task = task_store.get_task(task_id)
    if not task:
        raise RuntimeError(f"Task {task_id} not found")

    branch_name = task.get("branch_name")
    if not branch_name:
        raise RuntimeError(f"Task {task_id} has no branch_name")

    # Default title and body from task
    if not title:
        title = task.get("title") or f"Task {task_id}"
    if not body:
        body = (task.get("description") or "") + f"\n\nTask: {task_id}"

    # Push the branch first
    push_branch(branch_name, project_path)

    # Create PR using gh CLI
    try:
        cmd = [
            "gh",
            "pr",
            "create",
            "--title",
            str(title),
            "--body",
            str(body),
            "--head",
            str(branch_name),
        ]
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"gh pr create failed: {result.stderr}")

        # Extract PR URL from output
        pr_url = result.stdout.strip()

        # Update task with PR URL and transition to ai_reviewing
        task_store.update_task(task_id, pull_request_url=pr_url)
        task_store.update_task_status(task_id, "ai_reviewing")

        logger.info("pr_created", task_id=task_id, pr_url=pr_url)

        return {
            "pr_url": pr_url,
            "branch_name": branch_name,
        }

    except FileNotFoundError as e:
        raise RuntimeError("gh CLI not installed - required for PR creation") from e
    except subprocess.SubprocessError as e:
        raise RuntimeError(f"Failed to create PR: {e}") from e


def _build_pr_body(task: dict[str, Any]) -> str:
    """Build the PR body.

    Args:
        task: Task dict

    Returns:
        Formatted PR body as markdown
    """
    lines = ["## Summary\n"]

    # Add task description
    desc = task.get("description", "")
    if desc:
        lines.append(f"{desc}\n")

    # Add task metadata
    lines.append("\n## Task Info\n")
    lines.append(f"- **Task ID:** `{task.get('id', 'N/A')}`")
    lines.append(f"- **Status:** {task.get('status', 'N/A')}")

    # Add commits if any
    commits = task.get("commits", [])
    if commits:
        lines.append(f"- **Commits:** {len(commits)}")

    # Add footer
    lines.append("\n---")
    lines.append("🤖 Generated with [SummitFlow](https://dev.summitflow.dev)")

    return "\n".join(lines)


def _get_existing_pr_url(branch_name: str, project_path: str | Path) -> str | None:
    """Get the URL of an existing PR for a branch.

    Args:
        branch_name: Branch to look for
        project_path: Path to the git repository

    Returns:
        PR URL if found, None otherwise
    """
    project_path = Path(project_path)

    result = subprocess.run(
        ["gh", "pr", "view", branch_name, "--json", "url", "-q", ".url"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _store_pr_url(task_id: str | None, pr_url: str) -> None:
    """Store the PR URL in the task record.

    Args:
        task_id: Task ID to update
        pr_url: PR URL to store
    """
    if task_id:
        from ...storage import tasks as task_store

        task_store.update_task(task_id, pull_request_url=pr_url)
