"""Git service for task-related git operations.

Provides functions for:
- Creating task branches
- Getting current branch info
- Committing changes
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import tasks as task_store

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
) -> str | None:
    """Create a git branch for a task.

    Creates a new branch from the current HEAD with the naming convention:
    task/{task_id}-{slug}

    Args:
        task_id: The task ID (e.g., task-abc123)
        feature_title: The feature title to include in the branch name
        project_path: Path to the git repository

    Returns:
        The created branch name, or None if creation failed

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


def commit_changes(
    message: str,
    project_path: str | Path,
    add_all: bool = True,
) -> str | None:
    """Create a git commit with staged changes.

    Args:
        message: Commit message
        project_path: Path to the git repository
        add_all: Whether to add all changes before committing

    Returns:
        Commit SHA if successful, None if nothing to commit
    """
    project_path = Path(project_path)

    if add_all:
        # Stage all changes
        result = subprocess.run(
            ["git", "add", "-A"],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("git_add_failed", error=result.stderr)
            raise RuntimeError(f"Failed to stage changes: {result.stderr}")

    # Check if there are changes to commit
    check_result: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=project_path,
        capture_output=True,
    )

    if check_result.returncode == 0:
        # No changes staged
        logger.info("no_changes_to_commit")
        return None

    # Create commit
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=project_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("commit_failed", error=result.stderr)
        raise RuntimeError(f"Failed to commit: {result.stderr}")

    # Get commit SHA
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )

    commit_sha = result.stdout.strip()
    logger.info("commit_created", sha=commit_sha[:8])
    return commit_sha


def push_branch(
    branch_name: str,
    project_path: str | Path,
    set_upstream: bool = True,
) -> bool:
    """Push a branch to remote origin.

    Args:
        branch_name: Name of the branch to push
        project_path: Path to the git repository
        set_upstream: Whether to set upstream tracking (default True)

    Returns:
        True if successful

    Raises:
        RuntimeError: If push fails
    """
    project_path = Path(project_path)

    cmd = ["git", "push"]
    if set_upstream:
        cmd.extend(["-u", "origin", branch_name])
    else:
        cmd.extend(["origin", branch_name])

    result = subprocess.run(
        cmd,
        cwd=project_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("push_failed", branch=branch_name, error=result.stderr)
        raise RuntimeError(f"Failed to push branch: {result.stderr}")

    logger.info("branch_pushed", branch=branch_name)
    return True


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
    from ..storage import capabilities as capability_store

    project_path = Path(project_path)

    branch_name = task.get("branch_name")
    if not branch_name:
        logger.error("no_branch_for_pr", task_id=task.get("id"))
        raise RuntimeError("Task has no branch_name, cannot create PR")

    # Get capability info for PR content (TDD architecture)
    capability = None
    capability_id = task.get("capability_id")
    if capability_id:
        capability = capability_store.get_capability_by_id(capability_id)

    # Build PR title
    if capability:
        pr_title = f"{capability.get('name', 'Capability')} [{task.get('id', 'task')}]"
    else:
        pr_title = task.get("title", f"Task {task.get('id', '')}")

    # Build PR body with tests checklist
    pr_body = _build_pr_body(task, capability)

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


def _build_pr_body(task: dict[str, Any], capability: dict[str, Any] | None) -> str:
    """Build the PR body with tests checklist.

    Args:
        task: Task dict
        capability: Capability dict (may be None)

    Returns:
        Formatted PR body as markdown
    """
    from ..storage import tests as test_store

    lines = ["## Summary\n"]

    # Add capability description if available
    if capability:
        desc = capability.get("description", "")
        if desc:
            lines.append(f"{desc}\n")
        else:
            lines.append(f"Implementation of **{capability.get('name', 'capability')}**\n")
    else:
        desc = task.get("description", "")
        if desc:
            lines.append(f"{desc}\n")

    # Add tests checklist (TDD architecture)
    if capability:
        project_id = capability.get("project_id")
        cap_id = capability.get("capability_id")
        if project_id and cap_id:
            cap_tests = test_store.get_tests_for_capability(project_id, cap_id)
            if cap_tests:
                lines.append("\n## Tests\n")
                for t in cap_tests:
                    passes = t.get("passes", False)
                    checkbox = "[x]" if passes else "[ ]"
                    test_name = t.get("name", "Unknown test")
                    lines.append(f"- {checkbox} {test_name}")
                lines.append("")

    # Add task metadata
    lines.append("\n## Task Info\n")
    lines.append(f"- **Task ID:** `{task.get('id', 'N/A')}`")
    if capability:
        lines.append(f"- **Capability ID:** `{capability.get('capability_id', 'N/A')}`")
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
        task_store.update_task(task_id, pull_request_url=pr_url)


def get_current_commit(repo_path: Path | str) -> str:
    """Get the current HEAD commit SHA.

    Args:
        repo_path: Path to the git repository

    Returns:
        Full commit SHA
    """
    repo_path = Path(repo_path)

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to get current commit: {result.stderr}")

    return result.stdout.strip()


def capture_diff(
    repo_path: Path | str,
    base_sha: str,
    head_sha: str = "HEAD",
) -> str:
    """Capture git diff between two commits.

    Args:
        repo_path: Path to the git repository
        base_sha: Base commit SHA
        head_sha: Head commit SHA (default: HEAD)

    Returns:
        Unified diff output as string
    """
    repo_path = Path(repo_path)

    result = subprocess.run(
        ["git", "diff", f"{base_sha}..{head_sha}", "--unified=3"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to capture diff: {result.stderr}")

    return result.stdout


def get_diff_stats(
    repo_path: Path | str,
    base_sha: str,
    head_sha: str = "HEAD",
) -> dict[str, Any]:
    """Get statistics from a git diff.

    Args:
        repo_path: Path to the git repository
        base_sha: Base commit SHA
        head_sha: Head commit SHA (default: HEAD)

    Returns:
        Dict with files_changed, insertions, deletions
    """
    repo_path = Path(repo_path)

    result = subprocess.run(
        ["git", "diff", f"{base_sha}..{head_sha}", "--shortstat"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to get diff stats: {result.stderr}")

    stats = {
        "files_changed": 0,
        "insertions": 0,
        "deletions": 0,
    }

    # Parse output like: " 3 files changed, 10 insertions(+), 5 deletions(-)"
    output = result.stdout.strip()
    if output:
        # Extract numbers using regex
        files_match = re.search(r"(\d+) files? changed", output)
        insertions_match = re.search(r"(\d+) insertions?\(\+\)", output)
        deletions_match = re.search(r"(\d+) deletions?\(-\)", output)

        if files_match:
            stats["files_changed"] = int(files_match.group(1))
        if insertions_match:
            stats["insertions"] = int(insertions_match.group(1))
        if deletions_match:
            stats["deletions"] = int(deletions_match.group(1))

    return stats


def revert_to(repo_path: Path | str, sha: str) -> bool:
    """Hard reset repository to a specific commit.

    WARNING: This is destructive! All uncommitted changes will be lost.

    Args:
        repo_path: Path to the git repository
        sha: Commit SHA to reset to

    Returns:
        True if successful

    Raises:
        RuntimeError: If reset fails
    """
    repo_path = Path(repo_path)

    result = subprocess.run(
        ["git", "reset", "--hard", sha],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("revert_failed", sha=sha[:8], error=result.stderr)
        raise RuntimeError(f"Failed to revert to {sha}: {result.stderr}")

    logger.info("reverted", sha=sha[:8])
    return True


# =============================================================================
# Agent Workflow Automation
# =============================================================================


def auto_claim_with_worktree(
    task_id: str,
    project_path: str | Path,
    project_id: str,
) -> dict[str, Any]:
    """Claim a task and create an isolated worktree for agent execution.

    This is the entry point for agent workflows. It:
    1. Creates a worktree for the task
    2. Updates the task with worktree info
    3. Returns the worktree path for agent execution

    Args:
        task_id: Task ID to claim
        project_path: Path to main git repository
        project_id: Project ID for task lookups

    Returns:
        Dict with worktree_path, branch_name, and base_sha

    Raises:
        RuntimeError: If worktree creation fails
    """
    from .worktree_manager import WorktreeManager

    project_path = Path(project_path)
    manager = WorktreeManager(project_path)

    try:
        # Capture the base SHA before creating worktree (for rebase-resistant review)
        base_sha = get_head_sha(project_path)

        # Create worktree
        worktree_info = manager.create_worktree(project_id, task_id)

        # Update task with branch info (worktree path derivable from task_id)
        task_store.update_task(
            task_id,
            branch_name=worktree_info.branch,
            status="running",
        )

        logger.info(
            "agent_claim_complete",
            task_id=task_id,
            worktree=str(worktree_info.path),
            branch=worktree_info.branch,
        )

        return {
            "worktree_path": str(worktree_info.path),
            "branch_name": worktree_info.branch,
            "base_sha": base_sha,
        }

    except Exception as e:
        logger.error("agent_claim_failed", task_id=task_id, error=str(e))
        raise RuntimeError(f"Failed to claim task with worktree: {e}") from e


def get_head_sha(repo_path: str | Path) -> str:
    """Get the current HEAD commit SHA.

    Args:
        repo_path: Path to git repository

    Returns:
        Full commit SHA
    """
    repo_path = Path(repo_path)

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to get HEAD SHA: {result.stderr}")

    return result.stdout.strip()


def get_blob_shas(repo_path: str | Path, paths: list[str]) -> dict[str, str]:
    """Get blob SHAs for specific files (for rebase-resistant tracking).

    Args:
        repo_path: Path to git repository
        paths: List of file paths to get SHAs for

    Returns:
        Dict mapping file paths to their blob SHAs
    """
    repo_path = Path(repo_path)
    result: dict[str, str] = {}

    for path in paths:
        try:
            proc = subprocess.run(
                ["git", "ls-files", "-s", path],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                # Output format: <mode> <sha> <stage>\t<file>
                parts = proc.stdout.split()
                if len(parts) >= 2:
                    result[path] = parts[1]
        except subprocess.SubprocessError:
            pass  # Skip files that don't exist or error

    return result


def auto_create_pr(
    task_id: str,
    project_path: str | Path,
    title: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """Create a pull request from the task's worktree branch.

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


def get_worktree_changes(worktree_path: str | Path) -> dict[str, Any]:
    """Get summary of changes in a worktree.

    Args:
        worktree_path: Path to the worktree

    Returns:
        Dict with files_changed, additions, deletions, affected_files
    """
    worktree_path = Path(worktree_path)

    # Get diff stats against the base branch
    result = subprocess.run(
        ["git", "diff", "--stat", "HEAD~1..HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )

    # Parse the last line for summary (e.g., "3 files changed, 10 insertions(+), 5 deletions(-)")
    affected_files: list[str] = []
    stats: dict[str, Any] = {
        "files_changed": 0,
        "additions": 0,
        "deletions": 0,
        "affected_files": affected_files,
    }

    if result.returncode == 0:
        lines = result.stdout.strip().split("\n")

        # Get affected files (all lines except the last summary line)
        for line in lines[:-1]:
            parts = line.split("|")
            if len(parts) >= 1:
                file_path = parts[0].strip()
                if file_path:
                    stats["affected_files"].append(file_path)

        # Parse summary line
        if lines:
            summary = lines[-1]
            import re

            files_match = re.search(r"(\d+) files? changed", summary)
            ins_match = re.search(r"(\d+) insertions?", summary)
            del_match = re.search(r"(\d+) deletions?", summary)

            if files_match:
                stats["files_changed"] = int(files_match.group(1))
            if ins_match:
                stats["additions"] = int(ins_match.group(1))
            if del_match:
                stats["deletions"] = int(del_match.group(1))

    return stats
