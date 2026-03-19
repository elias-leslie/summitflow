"""Claim command for st CLI.

Checkpoint-aware task and subtask claiming with git+database checkpoints.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from app.storage.tasks import canonicalize_task_id

from ..client import APIError, STClient
from ..lib.checkpoint import (
    create_subtask_branch,
    create_task_snapshot,
    get_snapshot_info,
    remove_snapshot,
)
from ..output import output_error, output_success, output_warning
from .claim_helpers import (
    adopt_dirty_changes_to_worktree,
    handle_existing_checkpoint,
    is_subtask_id,
    print_claimed,
    print_resumed,
    require_claim_safe_tree,
)

app = typer.Typer(help="Claim task or subtask to start work")


def _claim_task(
    client: STClient,
    task_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Claim a task with checkpoint creation.

    Creates DB snapshot, git branch, and sets task status to running.
    """
    task_id = canonicalize_task_id(task_id)
    task = client.get_task(task_id)
    task_id = str(task.get("id", task_id))
    project_id = task.get("project_id", "")

    # Validate status before allocating worktree/ports
    status = task.get("status", "")
    claimable = ("pending", "failed")
    if status not in claimable and not force:
        output_error(f"Task {task_id} cannot be claimed (status={status}). Expected one of: {', '.join(claimable)}")
        raise typer.Exit(1)

    existing = get_snapshot_info(task_id)
    if existing and not force:
        return handle_existing_checkpoint(task_id, existing)

    require_claim_safe_tree()

    try:
        client.claim_task(task_id)
    except APIError as e:
        output_error(f"Failed to claim task: {e.detail}")
        raise typer.Exit(1) from None

    try:
        meta = create_task_snapshot(task_id, project_id)
    except Exception as e:
        remove_snapshot(task_id, remove_worktree=True, project_id=project_id)
        try:
            client.release_task(task_id)
        except Exception as release_error:
            output_warning(f"Failed to release task claim after snapshot error: {release_error}")
        output_error(f"Failed to create checkpoint: {e}")
        raise typer.Exit(1) from None

    if meta.worktree_path:
        try:
            adopt_dirty_changes_to_worktree(meta.worktree_path)
        except Exception as e:
            remove_snapshot(task_id, remove_worktree=True, project_id=project_id)
            try:
                client.release_task(task_id)
            except Exception as release_error:
                output_warning(f"Failed to release task claim after adoption error: {release_error}")
            output_error(f"Failed to adopt current changes into worktree: {e}")
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
    task_id = canonicalize_task_id(task_id)
    task = client.get_task(task_id)
    status = task.get("status", "")

    if status != "running":
        output_error(
            f"Parent task {task_id} not claimed (status={status}).\n"
            f"Run: st claim {task_id}"
        )
        raise typer.Exit(1)

    require_claim_safe_tree()
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

    if is_subtask_id(id):
        resolved_task_id = require_task_id(task_id)
        result = _claim_subtask(client, id, resolved_task_id)
        output_success(f"Subtask {id} claimed. Branch: {result['branch']}")
        return

    result = _claim_task(client, canonicalize_task_id(id), force)
    if result.get("action") == "resumed":
        print_resumed(id, result)
    else:
        print_claimed(id, result)


@app.command(name="adopt")
def adopt_command(
    task_id: Annotated[str | None, typer.Argument(help="Task ID with an existing claimed worktree")] = None,
) -> None:
    """Adopt current dirty changes into an already-claimed task worktree."""
    from ..context import require_task_id

    resolved_task_id = require_task_id(task_id)
    snapshot = get_snapshot_info(resolved_task_id)
    if not snapshot:
        output_error(f"No checkpoint found for {resolved_task_id}. Claim the task first.")
        raise typer.Exit(1)

    worktree_path = snapshot.get("worktree_path")
    if not worktree_path or not isinstance(worktree_path, str):
        output_error(f"Task {resolved_task_id} has no worktree to adopt into.")
        raise typer.Exit(1)

    try:
        adopted = adopt_dirty_changes_to_worktree(worktree_path)
    except Exception as e:
        output_error(f"Failed to adopt current changes into worktree: {e}")
        raise typer.Exit(1) from None

    if adopted == 0:
        output_warning("No current dirty paths needed adopting.")
        return
    output_success(f"Task {resolved_task_id} worktree updated from current repo state.")
