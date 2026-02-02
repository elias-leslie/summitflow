"""Done command for st CLI.

Checkpoint-aware completion for tasks and subtasks.
Merges git branches and cleans up DB snapshots.
"""

from __future__ import annotations

import subprocess
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..lib.checkpoint import (
    get_snapshot_info,
    merge_subtask_branch,
    merge_task_branch,
    remove_snapshot,
)
from ..output import output_error, output_success

app = typer.Typer(help="Complete task or subtask work")


def _is_subtask_id(id_str: str) -> bool:
    """Check if the ID looks like a subtask (e.g., 1.1, 2.3)."""
    if "." not in id_str:
        return False
    parts = id_str.split(".")
    if len(parts) != 2:
        return False
    return parts[0].isdigit() and parts[1].isdigit()


def _is_working_tree_clean(path: str | None = None) -> bool:
    """Check if git working tree is clean.

    Args:
        path: Directory to check. If None, checks current directory.
    """
    cmd = ["git", "status", "--porcelain"]
    if path:
        cmd = ["git", "-C", path, "status", "--porcelain"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return len(result.stdout.strip()) == 0
    except subprocess.CalledProcessError:
        return False


def _parse_db_error(detail: Any) -> str | None:
    """Parse DB trigger error messages into helpful guidance."""
    if not isinstance(detail, (str, dict)):
        return None

    msg = str(detail).lower() if isinstance(detail, str) else str(detail.get("detail", "")).lower()

    if "steps" in msg and ("incomplete" in msg or "not verified" in msg):
        return "Cannot complete: Some steps not verified. Run: st step pass <subtask> <step>"

    if "dependencies" in msg or "depends on" in msg:
        return "Cannot complete: Blocking dependencies incomplete. Complete them first."

    if "qa" in msg and ("pending" in msg or "signoff" in msg):
        return "Cannot complete: QA status pending. Run: st qa pass <task-id>"

    if "subtask" in msg and ("incomplete" in msg or "not all" in msg):
        return "Cannot complete task: Some subtasks incomplete. Run: st subtask list <task-id>"

    return None


def _complete_subtask(
    client: STClient,
    subtask_id: str,
    task_id: str,
    message: str | None = None,
) -> dict[str, Any]:
    """Complete a subtask with git branch merge.

    DB triggers verify all steps passed.
    """
    # Check working tree is clean
    if not _is_working_tree_clean():
        output_error("Working tree has uncommitted changes.\nCommit first: git commit -m 'message'")
        raise typer.Exit(1)

    # Get project_id from snapshot for per-project worktree paths
    snapshot_info = get_snapshot_info(task_id)
    project_id = snapshot_info.get("project_id") if snapshot_info else None

    # Mark subtask as passed via API (DB triggers verify steps)
    try:
        client.update_subtask(task_id, subtask_id, passes=True)
    except APIError as e:
        # Parse DB trigger errors
        detail: dict[str, Any] = (
            e.detail if isinstance(e.detail, dict) else {"detail": str(e.detail)}
        )
        helpful = _parse_db_error(detail)
        if helpful:
            output_error(helpful)
        else:
            output_error(f"Failed to complete subtask: {e.detail}")
        raise typer.Exit(1) from None

    # Merge subtask branch to task branch
    try:
        merge_subtask_branch(task_id, subtask_id, project_id=project_id)
    except SystemExit:
        # merge_subtask_branch already prints error
        output_error("Merge failed. Resolve conflicts manually, then retry.")
        raise typer.Exit(1) from None

    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "action": "completed",
        "merged": True,
    }


def _complete_task(
    client: STClient,
    task_id: str,
    message: str | None = None,
) -> dict[str, Any]:
    """Complete a task with branch merge and snapshot cleanup.

    DB triggers verify all subtasks passed and QA signoff.
    """
    # Check for existing checkpoint FIRST (need worktree path for clean check)
    snapshot_info = get_snapshot_info(task_id)
    if not snapshot_info:
        output_error(f"No checkpoint found for {task_id}. Was it claimed?")
        raise typer.Exit(1)

    # Check working tree is clean - check WORKTREE, not main repo
    worktree_path = snapshot_info.get("worktree_path")
    if worktree_path and not _is_working_tree_clean(worktree_path):
        output_error(
            f"Worktree has uncommitted changes.\n"
            f"  Path: {worktree_path}\n"
            f"Commit first: cd {worktree_path} && git commit -m 'message'"
        )
        raise typer.Exit(1)

    # Also check main repo - st done runs from main and needs it clean for merge
    if not _is_working_tree_clean():
        output_error(
            "Main repo has uncommitted changes.\nCommit or stash first before completing task."
        )
        raise typer.Exit(1)

    # Mark task as completed via API (DB triggers verify all subtasks)
    try:
        client.update_status(task_id, "completed")
    except APIError as e:
        # Parse DB trigger errors
        detail: dict[str, Any] = (
            e.detail if isinstance(e.detail, dict) else {"detail": str(e.detail)}
        )
        helpful = _parse_db_error(detail)
        if helpful:
            output_error(helpful)
        else:
            output_error(f"Failed to complete task: {e.detail}")
        raise typer.Exit(1) from None

    # Get project_id from snapshot for per-project worktree paths
    project_id = snapshot_info.get("project_id") if snapshot_info else None

    # Merge task branch to base branch
    try:
        merge_task_branch(task_id, project_id=project_id)
    except SystemExit:
        # merge_task_branch already prints error
        output_error("Merge failed. Resolve conflicts manually, then retry.")
        raise typer.Exit(1) from None

    # Remove snapshot after successful merge
    remove_snapshot(task_id, project_id=project_id)

    return {
        "task_id": task_id,
        "action": "completed",
        "merged": True,
        "snapshot_removed": True,
    }


@app.command(name="done")
def done_command(
    id: Annotated[str, typer.Argument(help="Task ID or subtask ID (e.g., 1.1)")],
    task_id: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Parent task ID (for subtask completion)"),
    ] = None,
    message: Annotated[
        str | None,
        typer.Option("--message", "-m", help="Completion message"),
    ] = None,
) -> None:
    """Complete a task or subtask.

    For subtasks: Verifies all steps passed (via DB trigger), merges branch.
    For tasks: Verifies all subtasks done (via DB trigger), merges branches, removes checkpoint.

    This creates a clean merge point and cleans up the checkpoint artifacts.

    Examples:
        st done 1.1 -t task-abc123   # Complete subtask 1.1
        st done 1.1                   # Uses active context
        st done task-abc123           # Complete entire task
    """
    from ..context import require_task_id

    client = STClient()

    # Determine if this is a task or subtask
    if _is_subtask_id(id):
        # Subtask completion - need task_id
        resolved_task_id = require_task_id(task_id)
        _complete_subtask(client, id, resolved_task_id, message)
        output_success(f"Subtask {id} completed. Branch merged.")
    else:
        _complete_task(client, id, message)
        output_success(f"Task {id} completed. Checkpoint removed.")
        typer.echo(f"  Merged to: {get_snapshot_info(id) or 'main'}")
