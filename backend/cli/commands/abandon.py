"""Abandon command for st CLI.

Checkpoint-aware rollback for tasks and subtasks.
For tasks, restores DB snapshot and deletes all branches.
For subtasks, deletes git branch only.
"""

from __future__ import annotations

import subprocess
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..lib.checkpoint import (
    delete_subtask_branch,
    delete_task_branches,
    get_snapshot_info,
    remove_snapshot,
    restore_task_snapshot,
)
from ..output import output_error, output_success

app = typer.Typer(help="Abandon task or subtask work and rollback")


def _is_subtask_id(id_str: str) -> bool:
    """Check if the ID looks like a subtask (e.g., 1.1, 2.3)."""
    if "." not in id_str:
        return False
    parts = id_str.split(".")
    if len(parts) != 2:
        return False
    return parts[0].isdigit() and parts[1].isdigit()


def _get_subtask_branches(task_id: str) -> list[str]:
    """Get all subtask branches for a task."""
    try:
        result = subprocess.run(
            ["git", "branch", "--list", f"{task_id}/*"],
            capture_output=True,
            text=True,
            check=True,
        )
        branches = []
        for line in result.stdout.splitlines():
            branch = line.strip().lstrip("* ")
            if branch:
                branches.append(branch)
        return branches
    except subprocess.CalledProcessError:
        return []


def _abandon_subtask(
    client: STClient,
    subtask_id: str,
    task_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Abandon a subtask - delete git branch only.

    Does not affect DB (other subtasks may have made changes).
    """
    branch_name = f"{task_id}/{subtask_id}"

    # Check if branch exists
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", branch_name],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            output_error(f"Branch {branch_name} does not exist.")
            raise typer.Exit(1)
    except subprocess.CalledProcessError:
        output_error(f"Branch {branch_name} does not exist.")
        raise typer.Exit(1) from None

    # Reset subtask status via API (clear assignee, passes=false)
    try:
        client.update_subtask(task_id, subtask_id, passes=False)
    except APIError as e:
        # Non-fatal - branch deletion is more important
        typer.echo(f"Warning: Could not reset subtask status: {e.detail}", err=True)

    # Delete subtask branch
    if not delete_subtask_branch(task_id, subtask_id):
        output_error(f"Failed to delete branch {branch_name}")
        raise typer.Exit(1)

    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "action": "abandoned",
        "branch_deleted": branch_name,
    }


def _abandon_task(
    client: STClient,
    task_id: str,
    force: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    """Abandon a task - restore DB snapshot and delete all branches.

    This is destructive: restores database to pre-task state.
    """
    # Check for existing checkpoint
    snapshot_info = get_snapshot_info(task_id)
    if not snapshot_info:
        output_error(f"No checkpoint found for {task_id}. Nothing to restore.")
        raise typer.Exit(1)

    # Check for active subtask branches
    subtask_branches = _get_subtask_branches(task_id)
    if subtask_branches and not force:
        typer.echo(f"Warning: Found {len(subtask_branches)} subtask branches:", err=True)
        for branch in subtask_branches[:5]:
            typer.echo(f"  - {branch}", err=True)
        if len(subtask_branches) > 5:
            typer.echo(f"  ... and {len(subtask_branches) - 5} more", err=True)

    # Confirmation for task-level abandon
    if not force:
        typer.echo("\nThis will:")
        typer.echo(f"  - Restore DB to pre-task state (snapshot: {snapshot_info.get('size', '?')})")
        typer.echo(f"  - Delete task branch: {task_id}")
        if subtask_branches:
            typer.echo(f"  - Delete {len(subtask_branches)} subtask branches")
        typer.echo("")
        confirm = typer.confirm("Proceed with abandon?", default=False)
        if not confirm:
            typer.echo("Aborted.")
            raise typer.Exit(0)

    # Restore DB from snapshot (stops/starts backend)
    try:
        restore_task_snapshot(task_id)
    except SystemExit:
        output_error(
            f"DB restore failed. Snapshot preserved at .st/snapshots/{task_id}.sql\n"
            "You can manually restore with: pg_restore --clean --dbname=<url> <snapshot>"
        )
        raise typer.Exit(1) from None

    # Delete all task branches
    delete_task_branches(task_id)

    # Remove snapshot files
    remove_snapshot(task_id)

    # Reset task status via API
    try:
        client.update_status(task_id, "todo")
    except APIError as e:
        # Non-fatal - DB/branches already restored
        typer.echo(f"Warning: Could not reset task status: {e.detail}", err=True)

    return {
        "task_id": task_id,
        "action": "abandoned",
        "db_restored": True,
        "branches_deleted": len(subtask_branches) + 1,
        "snapshot_removed": True,
    }


@app.command(name="abandon")
def abandon_command(
    id: Annotated[str, typer.Argument(help="Task ID or subtask ID (e.g., 1.1)")],
    task_id: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Parent task ID (for subtask abandonment)"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation (for task-level abandon)"),
    ] = False,
    reason: Annotated[
        str | None,
        typer.Option("--reason", "-r", help="Reason for abandonment"),
    ] = None,
) -> None:
    """Abandon a task or subtask and rollback changes.

    For subtasks: Deletes git branch only (DB unchanged).
    For tasks: Restores DB snapshot, deletes all branches.

    DESTRUCTIVE: Task-level abandon restores the database to its state
    before the task was claimed. All changes made during the task are lost.

    Examples:
        st abandon 1.1 -t task-abc123    # Abandon subtask (delete branch)
        st abandon 1.1                    # Uses active context
        st abandon task-abc123            # Abandon task (restore DB, interactive)
        st abandon task-abc123 --force    # Abandon task (skip confirmation)
    """
    from ..context import require_task_id

    client = STClient()

    # Determine if this is a task or subtask
    if _is_subtask_id(id):
        # Subtask abandonment - need task_id
        resolved_task_id = require_task_id(task_id)
        result = _abandon_subtask(client, id, resolved_task_id, reason)
        output_success(f"Subtask {id} abandoned. Branch deleted.")
    else:
        # Task abandonment
        result = _abandon_task(client, id, force, reason)
        output_success(f"Task {id} abandoned. DB restored, branches deleted.")
