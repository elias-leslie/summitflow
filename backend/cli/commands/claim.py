"""Claim command for st CLI.

Checkpoint-aware task and subtask claiming with git+metadata checkpoints.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from app.services.task_lane_preflight import check_task_lane_conflicts
from app.storage.tasks import canonicalize_task_id

from ..client import APIError, STClient
from ..lib.checkpoint import (
    create_subtask_branch,
    create_task_snapshot,
    get_snapshot_info,
    remove_snapshot,
)
from ..lib.usage import usage
from ..output import output_error, output_success, output_warning
from .claim_helpers import (
    handle_existing_checkpoint,
    is_subtask_id,
    print_claimed,
    print_resumed,
    require_claim_safe_tree,
)
from .pulse import require_pulse_gate

app = typer.Typer(help="Claim task or subtask to start work")


def _require_task_lane_clear(task_id: str, project_id: str | None) -> None:
    """Block only exact task-lane conflicts, not project-level session presence."""
    if not project_id:
        return
    lane_check = check_task_lane_conflicts(task_id, project_id)
    if lane_check.disposition != "block":
        return
    for issue in lane_check.issues:
        output_error(issue)
    raise typer.Exit(2)


def _claim_task(
    client: STClient,
    task_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Claim a task with checkpoint creation.

    Creates checkpoint metadata, a git branch, and sets task status to running.
    """
    task_id = canonicalize_task_id(task_id)
    task = client.get_task(task_id)
    task_id = str(task.get("id", task_id))
    project_id = task.get("project_id", "")

    status = task.get("status", "")
    claimable = ("pending", "paused", "failed")
    if status not in claimable and not force:
        output_error(f"Task {task_id} cannot be claimed (status={status}). Expected one of: {', '.join(claimable)}")
        raise typer.Exit(1)

    existing = get_snapshot_info(task_id)
    if existing and not force:
        require_pulse_gate(str(project_id) if project_id else None)
        _require_task_lane_clear(task_id, str(project_id) if project_id else None)
        require_claim_safe_tree()
        try:
            client.claim_task(task_id)
        except APIError as e:
            output_error(f"Failed to claim task: {e.detail}")
            raise typer.Exit(1) from None
        return handle_existing_checkpoint(task_id, existing)

    require_pulse_gate(str(project_id) if project_id else None)
    _require_task_lane_clear(task_id, str(project_id) if project_id else None)
    require_claim_safe_tree()

    try:
        client.claim_task(task_id)
    except APIError as e:
        output_error(f"Failed to claim task: {e.detail}")
        raise typer.Exit(1) from None

    try:
        meta = create_task_snapshot(task_id, project_id)
    except Exception as e:
        remove_snapshot(task_id, project_id=project_id)
        try:
            client.release_task(task_id)
        except Exception as release_error:
            output_warning(f"Failed to release task claim after snapshot error: {release_error}")
        output_error(f"Failed to create checkpoint: {e}")
        raise typer.Exit(1) from None

    return {
        "task_id": task_id,
        "action": "claimed",
        "branch": f"{task_id}/main",
        "base_branch": meta.base_branch,
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
@usage(
    surface="st.claim",
    cmd="st claim <task-id>",
    when="before any work on a task; after st ready picks one",
    precautions=(
        "subtask form uses dotted ID like 1.2; pass --task <parent> when claiming subtask",
        "claim creates a checkpoint and branch; one claim per agent at a time",
        "if blocked by lane conflict, fix the conflict — do not --force without reason",
    ),
    tier="mandate",
)
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

    Check global lane truth before claiming:
        st pulse

    For tasks: Creates checkpoint metadata and a git branch.
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
