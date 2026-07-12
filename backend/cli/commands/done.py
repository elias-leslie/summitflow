"""Done command for st CLI.

Checkpoint-aware completion for tasks and subtasks.
Publishes direct-main work and cleans up checkpoint metadata.

Smart default: auto-verifies, checkpoints, publishes, closes, and cleans up.
Use --strict for old gate-check-only behavior.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import STClient
from ..lib.checkpoint import get_snapshot_info
from ..lib.usage import usage
from ..output import output_error, output_success
from .done_subtask import complete_subtask
from .done_task import complete_task
from .done_validators import is_subtask_id
from .preflight import preflight

app = typer.Typer(help="Complete task or subtask work")


def _is_autocode_dispatch_claim(claimed_by: object) -> bool:
    """Return whether the claim belongs to the autocode dispatcher."""
    return isinstance(claimed_by, str) and claimed_by.startswith("api-dispatch-")


def _handle_subtask_completion(
    client: STClient,
    id: str,
    task_id: str | None,
    message: str | None,
    citations: list[str] | None = None,
    acknowledge_none: bool = False,
) -> None:
    """Handle subtask completion (idempotent; records citations if provided)."""
    from ..context import require_task_id

    resolved_task_id = require_task_id(task_id)
    result = complete_subtask(
        client, id, resolved_task_id, message,
        citations=citations, acknowledge_none=acknowledge_none,
    )
    if result.get("action") == "noop":
        output_success(f"Subtask {id} already complete (no-op).")
        return
    output_success(f"Subtask {id} completed. Metadata updated.")


def _refuse_if_autocode_owned(task: dict[str, object], task_id: str) -> None:
    """Refuse st done while an autocode dispatcher actively owns the claim.

    The autocode orchestrator owns terminal-status transitions for tasks it runs.
    When an autocode agent reflexively calls `st done` as its closing move, it
    races the orchestrator's closeout gates and publish step.
    """
    claimed_by = task.get("claimed_by")
    if not _is_autocode_dispatch_claim(claimed_by):
        return
    lock_expires_at = task.get("lock_expires_at")
    expires = str(lock_expires_at) if lock_expires_at else ""
    output_error(
        f"Task {task_id} is claimed by '{claimed_by}'"
        + (f" (lock expires {expires})." if expires else ".")
        + "\n  The autocode dispatcher owns completion for this task."
        + "\n  Return control and let the post-execution gates run."
    )
    raise typer.Exit(1)


def _release_task_leases(project_id: str | None, task_id: str) -> None:
    """Best-effort release of leases tied to a completed task.

    Never blocks closeout: a lease-store hiccup must not fail a finished task.
    """
    if not project_id:
        return
    try:
        from ..lib.leases import release_task

        released = release_task(project_id, task_id)
    except Exception:
        return
    if released:
        output_success(f"Released {released} lease(s) held for {task_id}.")


def _handle_task_completion(
    client: STClient,
    id: str,
    message: str | None,
) -> None:
    """Handle task completion (idempotent; docs/admin auto-routed)."""
    task = client.get_task(id)
    status = str(task.get("status") or "")
    if status == "completed" and not get_snapshot_info(id):
        output_success(f"Task {id} already complete (no-op).")
        return
    _refuse_if_autocode_owned(task, id)
    project_id = str(task.get("project_id") or "") or None
    preflight(id, project_id, op="done")
    task_client = STClient(project_id=project_id) if project_id else client
    result = complete_task(task_client, id, message)
    base_branch = result.get("base_branch", "main")
    if result.get("snapshot_removed"):
        output_success(f"Task {id} completed. Checkpoint removed.")
        typer.echo(f"  Closed on: {base_branch}")
    else:
        output_success(f"Task {id} completed.")
    _release_task_leases(project_id, id)


@app.command(name="done")
@usage(
    surface="st.done",
    cmd='st done <task-id> -m "summary"',
    when="assigned-task closeout (publish + checks + checkpoint + cleanup in one)",
    precautions=(
        "use st commit/st jj only when st done names them as blockers, or for off-task work",
        "never split closeout unless st done explicitly blocks",
    ),
    tier="mandate",
)
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
    citation: Annotated[
        list[str] | None,
        typer.Option(
            "--citation",
            help=(
                "Memory citation (subtask form): M:abc12345, G:abc12345, "
                "or 'Applied: [M:abc12345]'. Repeat for multiple."
            ),
        ),
    ] = None,
    acknowledge_none: Annotated[
        bool,
        typer.Option("--none", help="Acknowledge no memories were needed (subtask form)."),
    ] = False,
) -> None:
    """Complete a task or subtask.

    Auto-verifies, checkpoints, publishes, closes, and cleans up. Docs/config-only
    diffs are detected automatically; admin/no-merge paths are routed by DB state.
    Escape hatch: `ST_DIFF_GATE=off` for emergencies.

    Subtasks: pass --citation or --none to record memory citations before close.
    Already-completed task/subtask is a no-op (exit 0).
    """
    if is_subtask_id(id):
        client = STClient()
        _handle_subtask_completion(
            client, id, task_id, message,
            citations=citation, acknowledge_none=acknowledge_none,
        )
    else:
        if citation or acknowledge_none:
            output_error(
                "--citation / --none only apply to subtask completion.\n"
                "Resolution: pass them with a subtask id, e.g. st done 1.2 -t <task-id> --citation M:abc12345"
            )
            raise typer.Exit(1)
        client = STClient(require_project=False)
        _handle_task_completion(client, id, message)
