"""Helper functions for claim command.

Internal helpers split out to keep claim.py under 150 lines.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import Any

import typer

from ..output import output_error, output_success


def is_subtask_id(id_str: str) -> bool:
    """Check if the ID looks like a subtask (e.g., 1.1, 2.3)."""
    if "." not in id_str:
        return False
    parts = id_str.split(".")
    return len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()


def is_working_tree_clean() -> bool:
    """Check if git working tree is clean."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        return len(result.stdout.strip()) == 0
    except subprocess.CalledProcessError:
        return False


def require_clean_tree() -> None:
    """Exit with error if working tree has uncommitted changes."""
    if not is_working_tree_clean():
        output_error(
            "Working tree has uncommitted changes.\n"
            "Commit or stash first: git stash or git commit"
        )
        raise typer.Exit(1)


def _format_age(created_at: str) -> str:
    """Return human-readable age string from ISO timestamp."""
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    age = datetime.now(UTC) - created
    hours = int(age.total_seconds() / 3600)
    mins = int((age.total_seconds() % 3600) / 60)
    return f"{hours}h {mins}m" if hours > 0 else f"{mins}m"


def _resume_from_worktree(task_id: str, existing: dict[str, Any]) -> dict[str, Any]:
    """Resume a task that already has a live worktree."""
    return {
        "task_id": task_id,
        "action": "resumed",
        "branch": f"{task_id}/main",
        "worktree_path": existing.get("worktree_path"),
        "backend_port": existing.get("backend_port"),
        "frontend_port": existing.get("frontend_port"),
    }


def _resume_via_branch(task_id: str, worktree_path: str | None) -> dict[str, Any]:
    """Resume a task by checking out its branch (legacy / missing worktree)."""
    task_branch = f"{task_id}/main"
    try:
        subprocess.run(
            ["git", "checkout", task_branch],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        output_error(f"Failed to checkout branch: {e.stderr}")
        raise typer.Exit(1) from None
    return {"task_id": task_id, "action": "resumed", "branch": task_branch, "worktree_path": worktree_path}


def handle_existing_checkpoint(task_id: str, existing: dict[str, Any]) -> dict[str, Any]:
    """Prompt user about an existing checkpoint and either resume or abort."""
    age_str = _format_age(str(existing["created_at"]))
    typer.echo(f"Existing checkpoint found for {task_id} (created {age_str} ago).")
    typer.echo(f"Size: {existing.get('size', 'unknown')}")
    if existing.get("worktree_path"):
        typer.echo(f"Worktree: {existing['worktree_path']}")
    if not typer.confirm("Resume existing work?", default=True):
        typer.echo("Aborting. Use --force to overwrite.")
        raise typer.Exit(1)
    worktree_path = existing.get("worktree_path")
    if worktree_path and existing.get("worktree_exists") == "true":
        return _resume_from_worktree(task_id, existing)
    return _resume_via_branch(task_id, worktree_path)


def print_worktree_info(task_id: str, result: dict[str, Any]) -> None:
    """Print worktree path and optional isolated-service instructions."""
    typer.echo(f"  Worktree: {result['worktree_path']}")
    typer.echo("\nTo work in isolation:")
    typer.echo(f"  cd {result['worktree_path']}")
    if result.get("backend_port") and result.get("frontend_port"):
        typer.echo("\nTo start isolated services:")
        typer.echo(f"  worktree-services.sh start {task_id}")
        typer.echo(f"  Backend:  http://localhost:{result['backend_port']}")
        typer.echo(f"  Frontend: http://localhost:{result['frontend_port']}")


def print_resumed(task_id: str, result: dict[str, Any]) -> None:
    """Print output for a resumed task."""
    output_success(f"Task {task_id} resumed. Branch: {result['branch']}")
    if result.get("worktree_path"):
        print_worktree_info(task_id, result)


def print_claimed(task_id: str, result: dict[str, Any]) -> None:
    """Print output for a newly claimed task."""
    output_success(f"Task {task_id} claimed. Checkpoint created.")
    typer.echo(f"  Branch: {result['branch']}")
    if result.get("worktree_path"):
        print_worktree_info(task_id, result)
