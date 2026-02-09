"""Abandon command for st CLI.

Safe rollback for tasks and subtasks.
For tasks: Marks as abandoned, deletes git branches (NO DB restore).
For subtasks: Deletes git branch only.

IMPORTANT: This uses append-only task metadata. Tasks are NEVER deleted,
only marked as 'abandoned'. This prevents data loss when other tasks were
created after this task's checkpoint.
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
)
from ..output import output_error, output_success

app = typer.Typer(help="Abandon task or subtask work and rollback")


def _count_unmerged_commits(task_id: str) -> int:
    """Count commits on task branch that are not in main/master."""
    branch_name = f"{task_id}/main"
    for base in ("main", "master"):
        try:
            result = subprocess.run(
                ["git", "rev-list", "--count", f"{base}..{branch_name}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError):
            continue
    return 0


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
    discard: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    """Abandon a task - mark as abandoned and delete git branches.

    SAFE: Does NOT restore database. Uses append-only task metadata.
    Tasks created after this task's checkpoint will NOT be destroyed.
    """
    # Check for existing checkpoint
    snapshot_info = get_snapshot_info(task_id)
    has_snapshot = snapshot_info is not None

    # Safety check: warn about unmerged commits
    unmerged = _count_unmerged_commits(task_id)
    if unmerged > 0 and not discard:
        output_error(
            f"DESTRUCTIVE: Branch {task_id}/main has {unmerged} commits not in main.\n"
            f"  Proceeding will permanently delete this work.\n"
            f"  Use --discard to confirm, or `st done {task_id}` to merge first."
        )
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
        typer.echo(f"  - Mark task {task_id} as 'abandoned'")
        typer.echo(f"  - Delete task branch: {task_id}/main")
        if subtask_branches:
            typer.echo(f"  - Delete {len(subtask_branches)} subtask branches")
        if has_snapshot and snapshot_info:
            typer.echo(f"  - Remove snapshot file ({snapshot_info.get('size', '?')})")
        if unmerged > 0:
            typer.echo(f"  - DISCARD {unmerged} unmerged commits")
        typer.echo("")
        typer.echo("NOTE: Database will NOT be restored (append-only task metadata).")
        typer.echo("")
        confirm = typer.confirm("Proceed with abandon?", default=False)
        if not confirm:
            typer.echo("Aborted.")
            raise typer.Exit(0)

    # Mark task as abandoned (NOT pending - this is a terminal state)
    try:
        client.update_status(task_id, "abandoned")
    except APIError as e:
        typer.echo(f"Warning: Could not update task status: {e.detail}", err=True)

    # Get project_id from snapshot for per-project worktree paths
    raw_pid = snapshot_info.get("project_id") if snapshot_info else None
    project_id: str | None = str(raw_pid) if raw_pid is not None else None

    # Remove worktree FIRST (so branches aren't "in use" by worktree)
    if has_snapshot:
        remove_snapshot(task_id, remove_worktree=True, project_id=project_id)

    # Delete all task branches (code rollback only)
    delete_task_branches(task_id)

    return {
        "task_id": task_id,
        "action": "abandoned",
        "db_restored": False,  # NEVER restore DB
        "branches_deleted": len(subtask_branches) + 1,
        "snapshot_removed": has_snapshot,
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
    discard: Annotated[
        bool,
        typer.Option("--discard", help="Confirm deletion of unmerged commits"),
    ] = False,
    reason: Annotated[
        str | None,
        typer.Option("--reason", "-r", help="Reason for abandonment"),
    ] = None,
) -> None:
    """Abandon a task or subtask and rollback code changes.

    For subtasks: Deletes git branch only.
    For tasks: Marks as 'abandoned', deletes all branches.

    If the task branch has unmerged commits, --discard is required to confirm
    you want to permanently delete that work. Use 'st done' to merge first.

    SAFE: Database is NOT restored. This uses append-only task metadata,
    preventing data loss when other tasks were created after this task's
    checkpoint was taken.

    Examples:
        st abandon 1.1 -t task-abc123          # Abandon subtask (delete branch)
        st abandon task-abc123                  # Abandon task (interactive)
        st abandon task-abc123 --force          # Skip confirmation
        st abandon task-abc123 --discard        # Confirm discarding unmerged work
        st abandon task-abc123 --discard --force  # Skip all prompts
    """
    from ..context import require_task_id

    client = STClient()

    # Determine if this is a task or subtask
    if _is_subtask_id(id):
        # Subtask abandonment - need task_id
        resolved_task_id = require_task_id(task_id)
        _abandon_subtask(client, id, resolved_task_id, reason)
        output_success(f"Subtask {id} abandoned. Branch deleted.")
    else:
        _abandon_task(client, id, force, discard, reason)
        output_success(f"Task {id} abandoned. Branches deleted, status set to 'abandoned'.")
