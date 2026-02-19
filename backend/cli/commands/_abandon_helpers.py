"""Helper functions and core logic for the abandon command."""

from __future__ import annotations

import subprocess

import typer

from ..client import APIError, STClient
from ..lib.checkpoint import (
    delete_subtask_branch,
    delete_task_branches,
    get_snapshot_info,
    remove_snapshot,
)
from ..output import output_error


def count_unmerged_commits(task_id: str) -> int:
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


def is_subtask_id(id_str: str) -> bool:
    """Check if the ID looks like a subtask (e.g., 1.1, 2.3)."""
    if "." not in id_str:
        return False
    parts = id_str.split(".")
    if len(parts) != 2:
        return False
    return parts[0].isdigit() and parts[1].isdigit()


def get_subtask_branches(task_id: str) -> list[str]:
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


def check_branch_exists(branch_name: str) -> bool:
    """Return True if git branch exists, False otherwise."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", branch_name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def confirm_task_abandon(
    task_id: str,
    subtask_branches: list[str],
    has_snapshot: bool,
    snapshot_info: dict[str, object] | None,
    unmerged: int,
) -> None:
    """Display abandon summary and prompt user to confirm. Exits on cancel."""
    if subtask_branches:
        typer.echo(f"Warning: Found {len(subtask_branches)} subtask branches:", err=True)
        for branch in subtask_branches[:5]:
            typer.echo(f"  - {branch}", err=True)
        if len(subtask_branches) > 5:
            typer.echo(f"  ... and {len(subtask_branches) - 5} more", err=True)

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
    if not typer.confirm("Proceed with abandon?", default=False):
        typer.echo("Aborted.")
        raise typer.Exit(0)


def abandon_subtask(
    client: STClient,
    subtask_id: str,
    task_id: str,
    reason: str | None = None,
) -> dict[str, object]:
    """Abandon a subtask - delete git branch only.

    Does not affect DB (other subtasks may have made changes).
    """
    branch_name = f"{task_id}/{subtask_id}"
    if not check_branch_exists(branch_name):
        output_error(f"Branch {branch_name} does not exist.")
        raise typer.Exit(1)

    try:
        client.update_subtask(task_id, subtask_id, passes=False)
    except APIError as e:
        typer.echo(f"Warning: Could not reset subtask status: {e.detail}", err=True)

    if not delete_subtask_branch(task_id, subtask_id):
        output_error(f"Failed to delete branch {branch_name}")
        raise typer.Exit(1)

    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "action": "abandoned",
        "branch_deleted": branch_name,
    }


def abandon_task(
    client: STClient,
    task_id: str,
    force: bool = False,
    discard: bool = False,
    reason: str | None = None,
) -> dict[str, object]:
    """Abandon a task - mark as abandoned and delete git branches.

    SAFE: Does NOT restore database. Uses append-only task metadata.
    Tasks created after this task's checkpoint will NOT be destroyed.
    """
    snapshot_info = get_snapshot_info(task_id)
    has_snapshot = snapshot_info is not None
    unmerged = count_unmerged_commits(task_id)
    subtask_branches = get_subtask_branches(task_id)

    if unmerged > 0 and not discard:
        output_error(
            f"DESTRUCTIVE: Branch {task_id}/main has {unmerged} commits not in main.\n"
            f"  Proceeding will permanently delete this work.\n"
            f"  Use --discard to confirm, or `st done {task_id}` to merge first."
        )
        raise typer.Exit(1)

    if not force:
        confirm_task_abandon(task_id, subtask_branches, has_snapshot, snapshot_info, unmerged)

    try:
        client.update_status(task_id, "abandoned")
    except APIError as e:
        typer.echo(f"Warning: Could not update task status: {e.detail}", err=True)

    raw_pid = snapshot_info.get("project_id") if snapshot_info else None
    project_id: str | None = str(raw_pid) if raw_pid is not None else None

    if has_snapshot:
        remove_snapshot(task_id, remove_worktree=True, project_id=project_id)

    delete_task_branches(task_id)

    return {
        "task_id": task_id,
        "action": "abandoned",
        "db_restored": False,
        "branches_deleted": len(subtask_branches) + 1,
        "snapshot_removed": has_snapshot,
    }
