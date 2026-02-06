"""Close command for st CLI.

Lightweight task completion for code-only tasks (no DB changes).
Marks task as completed and cleans up git branches and snapshot files.

Unlike `st done`, this command:
- Does NOT merge branches (just deletes them)
- Does NOT require all subtasks to be completed
- Does NOT restore or use checkpoint data

Use this for tasks that only modified code and don't need checkpoint merging.
"""

from __future__ import annotations

import subprocess
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..lib.checkpoint import (
    delete_task_branches,
    get_snapshot_info,
    remove_snapshot,
)
from ..output import output_error, output_success

app = typer.Typer(help="Close task (lightweight completion)")


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


def _close_task(
    client: STClient,
    task_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Close a task - mark as completed and delete git branches.

    Lightweight completion for code-only tasks:
    - Updates task status to 'completed'
    - Deletes all task branches (no merge)
    - Removes snapshot files (cleanup only)
    """
    # Check for existing checkpoint/snapshot
    snapshot_info = get_snapshot_info(task_id)
    has_snapshot = snapshot_info is not None

    # Check for active subtask branches
    subtask_branches = _get_subtask_branches(task_id)
    if subtask_branches and not force:
        typer.echo(f"Warning: Found {len(subtask_branches)} subtask branches:", err=True)
        for branch in subtask_branches[:5]:
            typer.echo(f"  - {branch}", err=True)
        if len(subtask_branches) > 5:
            typer.echo(f"  ... and {len(subtask_branches) - 5} more", err=True)

    # Confirmation for task-level close
    if not force:
        typer.echo("\nThis will:")
        typer.echo(f"  - Mark task {task_id} as 'completed'")
        typer.echo(f"  - Delete task branch: {task_id}/main (NO merge)")
        if subtask_branches:
            typer.echo(f"  - Delete {len(subtask_branches)} subtask branches (NO merge)")
        if has_snapshot:
            typer.echo(f"  - Remove snapshot file ({snapshot_info.get('size', '?')})")
        typer.echo("")
        typer.echo("NOTE: Branches will be DELETED, not merged. Use 'st done' for merge workflow.")
        typer.echo("")
        confirm = typer.confirm("Proceed with close?", default=False)
        if not confirm:
            typer.echo("Aborted.")
            raise typer.Exit(0)

    # Mark task as completed (skip gates — this is the cleanup path)
    try:
        client.update_status(task_id, "completed", skip_gates=True)
    except APIError as e:
        output_error(f"Failed to update task status: {e.detail}")
        raise typer.Exit(1) from None

    # Get project_id from snapshot for per-project worktree paths
    project_id = snapshot_info.get("project_id") if snapshot_info else None

    # Remove worktree + snapshot BEFORE branch deletion (worktree holds branch ref)
    if has_snapshot:
        remove_snapshot(task_id, remove_worktree=True, project_id=project_id)

    # Delete all task branches (code cleanup, no merge)
    delete_task_branches(task_id)

    return {
        "task_id": task_id,
        "action": "closed",
        "status": "completed",
        "branches_deleted": len(subtask_branches) + 1,
        "snapshot_removed": has_snapshot,
    }


@app.command(name="close")
def close_command(
    task_id: Annotated[str, typer.Argument(help="Task ID to close")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
) -> None:
    """Close a task (lightweight completion).

    Marks task as 'completed' and cleans up branches/snapshots.
    Unlike 'st done', this does NOT merge branches.

    Use this for code-only tasks that don't need checkpoint merging:
    - Quick fixes that were tested but not merged
    - Abandoned work that should still be marked complete
    - Tasks where you manually merged or cherry-picked changes

    Examples:
        st close task-abc123           # Close task (interactive)
        st close task-abc123 --force   # Close task (skip confirmation)
    """
    client = STClient()

    result = _close_task(client, task_id, force)
    branches_deleted = result.get("branches_deleted", 0)
    snapshot_removed = result.get("snapshot_removed", False)

    msg_parts = [f"Task {task_id} closed."]
    if branches_deleted > 0:
        msg_parts.append(f"{branches_deleted} branches deleted.")
    if snapshot_removed:
        msg_parts.append("Snapshot removed.")

    output_success(" ".join(msg_parts))
