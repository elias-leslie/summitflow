"""Claim command for st CLI.

Checkpoint-aware task and subtask claiming with git+metadata checkpoints.
"""

from __future__ import annotations

import os
from typing import Annotated, Any

import typer

from app.storage.tasks import canonicalize_task_id

from ..client import APIError, STClient
from ..lib.checkpoint import (
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
from .preflight import preflight

app = typer.Typer(help="Claim task or subtask to start work")


def _current_caller_id() -> str:
    """Identify the current caller for idempotent re-claim detection.

    Matches the worker_id convention used by `client.claim_task` (AGENT_ID env
    or whoami fallback). When both match the existing `claimed_by`, a re-claim
    is treated as a resumed success rather than a conflict.
    """
    explicit = os.getenv("AGENT_ID")
    if explicit:
        return explicit
    user = os.getenv("USER") or os.getenv("LOGNAME") or ""
    return user or "unknown"


def _is_same_caller(claimed_by: object) -> bool:
    if not isinstance(claimed_by, str) or not claimed_by:
        return False
    me = _current_caller_id()
    return bool(me) and (claimed_by == me)


def _enforce_plan_status_gate(task: dict[str, Any]) -> None:
    """Binary plan-status gate.

    - draft + autonomous → auto-promote to approved (autocode self-approval).
    - rejected → block with a resolution hint pointing at st context/update.
    - other states → pass-through.
    """
    plan_status = str(task.get("plan_status") or "draft")
    execution_mode = str(task.get("execution_mode") or "manual")
    task_id = str(task.get("id") or "")

    if plan_status == "rejected":
        output_error(
            f"Task {task_id} plan is rejected.\n"
            f"Resolution: st context {task_id} to review rejection, "
            f"then st update {task_id} --plan <new.json>"
        )
        raise typer.Exit(2)

    if plan_status == "draft" and execution_mode == "autonomous":
        try:
            from app.storage.task_spirit import approve_plan
        except Exception:
            return
        try:
            approve_plan(task_id, approved_by="st-claim-auto-promote")
            task["plan_status"] = "approved"
        except Exception as exc:
            output_warning(f"Plan auto-promotion failed for {task_id}: {exc}")


def _claim_task(
    client: STClient,
    task_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Claim a task with checkpoint creation.

    Idempotency: re-claiming a running task that is already claimed by the same
    caller returns a `resumed` success. Cross-agent conflicts still block.
    """
    task_id = canonicalize_task_id(task_id)
    task = client.get_task(task_id)
    task_id = str(task.get("id", task_id))
    project_id = task.get("project_id", "")
    pid_str = str(project_id) if project_id else None

    _enforce_plan_status_gate(task)

    status = task.get("status", "")
    existing = get_snapshot_info(task_id)

    # Idempotent re-claim: same caller, already running, existing checkpoint → resume.
    if status == "running" and existing and _is_same_caller(task.get("claimed_by")):
        return {
            "task_id": task_id,
            "action": "resumed",
            "base_branch": str(existing.get("base_branch", "main")),
        }

    if status == "running" and not force and not _is_same_caller(task.get("claimed_by")):
        claimed_by = task.get("claimed_by") or "another agent"
        output_error(
            f"Task {task_id} is already claimed by {claimed_by}.\n"
            f"Resolution: st pulse to inspect, or wait/coordinate with the holder."
        )
        raise typer.Exit(2)

    claimable = ("pending", "paused", "failed", "running")
    if status not in claimable and not force:
        output_error(
            f"Task {task_id} cannot be claimed (status={status}).\n"
            f"Resolution: st reopen {task_id} to move it back to pending, or pick a different task."
        )
        raise typer.Exit(1)

    if existing and not force:
        preflight(task_id, pid_str, op="claim")
        try:
            client.claim_task(task_id)
        except APIError as e:
            output_error(f"Failed to claim task: {e.detail}")
            raise typer.Exit(1) from None
        return handle_existing_checkpoint(task_id, existing)

    preflight(task_id, pid_str, op="claim")

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
        "base_branch": meta.base_branch,
    }


def _claim_subtask(
    client: STClient,
    subtask_id: str,
    task_id: str,
) -> dict[str, Any]:
    """Claim a subtask.

    Parent task must be claimed first. No branch is created; subtask work
    commits direct to main with file-level coordination via `st lease`.
    """
    task_id = canonicalize_task_id(task_id)
    task = client.get_task(task_id)
    status = task.get("status", "")

    if status != "running":
        output_error(
            f"Parent task {task_id} not claimed (status={status}).\n"
            f"Resolution: st claim {task_id}"
        )
        raise typer.Exit(1)

    require_claim_safe_tree()

    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "action": "claimed",
    }


@app.command(name="claim")
@usage(
    surface="st.claim",
    cmd="st claim <task-id>",
    when="before any work on a task; after st ready picks one",
    precautions=(
        "subtask form uses dotted ID like 1.2; pass --task <parent> when claiming subtask",
        "claim records a checkpoint; work commits direct to main, no branch is created",
        "cross-agent conflicts print a Resolution hint pointing at st pulse",
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

    Re-claiming by the same caller is idempotent (returns `resumed`). Use --force
    only to take over a stale claim from another agent.

    \b
    Examples:
      st claim task-abc123          # Claim task and record checkpoint metadata
      st claim 1.1 -t task-abc123   # Claim subtask 1.1
      st claim task-abc123 --force  # Take over a stale claim
    """
    from ..context import require_task_id

    client = STClient()

    if is_subtask_id(id):
        resolved_task_id = require_task_id(task_id)
        _claim_subtask(client, id, resolved_task_id)
        output_success(f"Subtask {id} claimed. Work commits direct to main.")
        return

    result = _claim_task(client, canonicalize_task_id(id), force)
    if result.get("action") == "resumed":
        print_resumed(id, result)
    else:
        print_claimed(id, result)
