"""Claim command for st CLI.

Checkpoint-aware task and subtask claiming with git+database checkpoints.
"""

from __future__ import annotations

import subprocess
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..lib.checkpoint import (
    create_subtask_branch,
    create_task_snapshot,
    get_snapshot_info,
)
from ..output import output_error, output_success

app = typer.Typer(help="Claim task or subtask to start work")


def _is_subtask_id(id_str: str) -> bool:
    """Check if the ID looks like a subtask (e.g., 1.1, 2.3)."""
    if "." not in id_str:
        return False
    parts = id_str.split(".")
    if len(parts) != 2:
        return False
    return parts[0].isdigit() and parts[1].isdigit()


def _is_working_tree_clean() -> bool:
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


def _claim_task(
    client: STClient,
    task_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Claim a task with checkpoint creation.

    Creates DB snapshot, git branch, and sets task status to running.
    """
    # Get project_id from task
    task = client.get_task(task_id)
    project_id = task.get("project_id", "")

    # Check for existing checkpoint (resume scenario)
    existing = get_snapshot_info(task_id)
    if existing and not force:
        from datetime import UTC, datetime

        created = datetime.fromisoformat(str(existing["created_at"]).replace("Z", "+00:00"))
        age = datetime.now(UTC) - created
        hours = int(age.total_seconds() / 3600)
        mins = int((age.total_seconds() % 3600) / 60)

        age_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"

        typer.echo(f"Existing checkpoint found for {task_id} (created {age_str} ago).")
        typer.echo(f"Size: {existing.get('size', 'unknown')}")
        if existing.get("worktree_path"):
            typer.echo(f"Worktree: {existing['worktree_path']}")
        resume = typer.confirm("Resume existing work?", default=True)
        if not resume:
            typer.echo("Aborting. Use --force to overwrite.")
            raise typer.Exit(1)
        # Resume - check for worktree or use branch
        worktree_path = existing.get("worktree_path")
        task_branch = f"{task_id}/main"
        if worktree_path and existing.get("worktree_exists") == "true":
            typer.echo(f"Resumed task {task_id}")
            return {
                "task_id": task_id,
                "action": "resumed",
                "branch": task_branch,
                "worktree_path": worktree_path,
                "backend_port": existing.get("backend_port"),
                "frontend_port": existing.get("frontend_port"),
            }
        # Fall back to branch checkout (legacy mode or missing worktree)
        try:
            subprocess.run(
                ["git", "checkout", task_branch],
                check=True,
                capture_output=True,
                text=True,
            )
            typer.echo(f"Resumed task {task_id}")
            return {
                "task_id": task_id,
                "action": "resumed",
                "branch": task_branch,
                "worktree_path": worktree_path,
            }
        except subprocess.CalledProcessError as e:
            output_error(f"Failed to checkout branch: {e.stderr}")
            raise typer.Exit(1) from None

    # Check working tree is clean
    if not _is_working_tree_clean():
        output_error(
            "Working tree has uncommitted changes.\nCommit or stash first: git stash or git commit"
        )
        raise typer.Exit(1)

    # Create checkpoint (DB snapshot + git branch)
    meta = create_task_snapshot(task_id, project_id)

    # Update task status to running via API
    try:
        client.update_status(task_id, "running")
    except APIError as e:
        # If status update fails (e.g., plan not approved), the DB trigger
        # will provide a helpful error message
        output_error(f"Failed to set status: {e.detail}")
        # We should probably rollback the checkpoint here, but for now
        # just let it be - user can abandon manually
        raise typer.Exit(1) from None

    return {
        "task_id": task_id,
        "action": "claimed",
        "branch": f"{task_id}/main",
        "base_branch": meta.base_branch,
        "worktree_path": meta.worktree_path,
        "backend_port": meta.backend_port,
        "frontend_port": meta.frontend_port,
    }


def _claim_subtask(
    client: STClient,
    subtask_id: str,
    task_id: str,
) -> dict[str, Any]:
    """Claim a subtask with git branch creation.

    Parent task must be claimed first.
    """
    # Get task to verify it's claimed (running)
    task = client.get_task(task_id)
    status = task.get("status", "")

    if status != "running":
        output_error(
            f"Parent task {task_id} not claimed (status={status}).\nRun: st claim {task_id}"
        )
        raise typer.Exit(1)

    # Check working tree is clean
    if not _is_working_tree_clean():
        output_error(
            "Working tree has uncommitted changes.\nCommit or stash first: git stash or git commit"
        )
        raise typer.Exit(1)

    # Create subtask branch
    branch_name = create_subtask_branch(task_id, subtask_id)

    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "action": "claimed",
        "branch": branch_name,
    }


@app.command(name="claim")
def claim_command(
    id: Annotated[str, typer.Argument(help="Task ID or subtask ID (e.g., 1.1)")],
    task_id: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Parent task ID (for subtask claims)"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Force claim, overwriting existing checkpoint"),
    ] = False,
) -> None:
    """Claim a task or subtask to start work.

    For tasks: Creates DB snapshot and git branch. Enforces one active task per project.
    For subtasks: Creates git branch only (parent task must be claimed first).

    This creates a checkpoint that enables safe rollback via 'st abandon'.

    Examples:
        st claim task-abc123         # Claim task, create checkpoint
        st claim 1.1 -t task-abc123  # Claim subtask 1.1
        st claim task-abc123 --force # Overwrite existing checkpoint
    """
    from ..context import require_task_id

    client = STClient()

    # Determine if this is a task or subtask
    if _is_subtask_id(id):
        # Subtask claim - need task_id
        resolved_task_id = require_task_id(task_id)
        result = _claim_subtask(client, id, resolved_task_id)
        output_success(f"Subtask {id} claimed. Branch: {result['branch']}")
    else:
        # Task claim
        result = _claim_task(client, id, force)
        if result.get("action") == "resumed":
            output_success(f"Task {id} resumed. Branch: {result['branch']}")
            if result.get("worktree_path"):
                typer.echo("\nTo work in isolation:")
                typer.echo(f"  cd {result['worktree_path']}")
                if result.get("backend_port") and result.get("frontend_port"):
                    typer.echo("\nTo start isolated services:")
                    typer.echo(f"  worktree-services.sh start {id}")
                    typer.echo(f"  Backend:  http://localhost:{result['backend_port']}")
                    typer.echo(f"  Frontend: http://localhost:{result['frontend_port']}")
        else:
            output_success(f"Task {id} claimed. Checkpoint created.")
            typer.echo(f"  Branch: {result['branch']}")
            if result.get("worktree_path"):
                typer.echo(f"  Worktree: {result['worktree_path']}")
                typer.echo("\nTo work in isolation:")
                typer.echo(f"  cd {result['worktree_path']}")
                if result.get("backend_port") and result.get("frontend_port"):
                    typer.echo("\nTo start isolated services:")
                    typer.echo(f"  worktree-services.sh start {id}")
                    typer.echo(f"  Backend:  http://localhost:{result['backend_port']}")
                    typer.echo(f"  Frontend: http://localhost:{result['frontend_port']}")
