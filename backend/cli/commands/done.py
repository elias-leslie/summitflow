"""Done command for st CLI.

Checkpoint-aware completion for tasks and subtasks.
Merges git branches and cleans up DB snapshots.

Smart default: auto-verifies, checkpoints, publishes, closes, and cleans up.
Use --strict for old gate-check-only behavior.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import STClient
from ..lib.usage import usage
from ..output import output_error, output_success
from .done_subtask import complete_subtask
from .done_task import complete_task
from .done_validators import is_subtask_id
from .pulse import require_pulse_gate

app = typer.Typer(help="Complete task or subtask work")


def _is_autocode_dispatch_claim(claimed_by: object) -> bool:
    """Return whether the claim belongs to the autocode dispatcher."""
    return isinstance(claimed_by, str) and claimed_by.startswith("api-dispatch-")


def _handle_subtask_completion(
    client: STClient,
    id: str,
    task_id: str | None,
    message: str | None,
) -> None:
    """Handle subtask completion."""
    from ..context import require_task_id

    resolved_task_id = require_task_id(task_id)
    complete_subtask(client, id, resolved_task_id, message)
    output_success(f"Subtask {id} completed. Branch merged.")


def _refuse_if_autocode_owned(task: dict[str, object], task_id: str, admin: bool) -> None:
    """Refuse st done while an autocode dispatcher actively owns the claim.

    The autocode orchestrator owns terminal-status transitions for tasks it
    runs. When an autocode agent reflexively calls `st done` as its closing
    move, it races the orchestrator and strands the work product on the task
    branch (see F2 'stuck-after-success'). The agent declares done by
    returning control; the orchestrator runs the diff/quality/runtime gates
    and transitions.
    """
    if admin:
        return
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
        + "\n  Override with --admin only if the claim is known stale."
    )
    raise typer.Exit(1)


def _handle_task_completion(
    client: STClient,
    id: str,
    message: str | None,
    strict: bool,
    admin: bool,
    skip_diff_gate: bool = False,
) -> None:
    """Handle task completion."""
    task = client.get_task(id)
    _refuse_if_autocode_owned(task, id, admin)
    project_id = str(task.get("project_id") or "") or None
    require_pulse_gate(project_id, allow_task_id=id)
    task_client = STClient(project_id=project_id) if project_id else client
    result = complete_task(task_client, id, message, strict=strict, admin=admin, skip_diff_gate=skip_diff_gate)
    if result.get("merged"):
        base_branch = result.get("base_branch", "main")
        output_success(f"Task {id} completed. Checkpoint removed.")
        typer.echo(f"  Merged to: {base_branch}")
    else:
        output_success(f"Task {id} completed without checkpoint merge.")
    require_pulse_gate(str(result.get("project_id") or project_id or "") or None, allow_task_id=id)


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
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Strict mode: fail on unpassed gates (old behavior)"),
    ] = False,
    admin: Annotated[
        bool,
        typer.Option(
            "--admin",
            help="Close task without checkpoint merge requirements (for meta/planning tasks)",
        ),
    ] = False,
    skip_diff_gate: Annotated[
        bool,
        typer.Option(
            "--skip-diff-gate",
            help="Skip diff gate check (for non-code tasks like docs or config)",
        ),
    ] = False,
) -> None:
    """Complete a task or subtask.

    Smart mode (default): auto-verifies, checkpoints, publishes, closes, and cleans up.
    Strict mode (--strict): fails if gates not pre-passed or main dirty.
    """
    if is_subtask_id(id):
        client = STClient()
        _handle_subtask_completion(client, id, task_id, message)
    else:
        client = STClient(require_project=False)
        _handle_task_completion(client, id, message, strict, admin, skip_diff_gate)
