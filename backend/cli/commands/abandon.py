"""Abandon command for st CLI.

Safe rollback for tasks and subtasks.
For tasks: Cancels task status, removes checkpoint metadata, and discards
tracked file changes after confirmation (NO DB restore).
For subtasks: Resets subtask status without requiring any branch.

Uses two-pass confirmation: first run shows blast radius and generates
a single-use token; second run with --confirm TOKEN executes.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import STClient
from ..lib.usage import usage
from ..output import output_success
from ._abandon_helpers import abandon_subtask, abandon_task, is_subtask_id

app = typer.Typer(help="Abandon task or subtask work and roll back tracked changes")


@app.command(name="abandon")
@usage(
    surface="st.abandon",
    cmd='st abandon <task-id> -r "reason"',
    when="discard a claimed task that won't be finished; rolls back code",
    precautions=(
        "commit before abandon — preview cannot recover uncommitted work",
        "two-pass confirm: first run shows blast radius + token; rerun with --confirm <token>",
        "use st cancel instead if you want to keep the record without rollback",
    ),
    tier="mandate",
)
def abandon_command(
    id: Annotated[str, typer.Argument(help="Task ID or subtask ID (e.g., 1.1)")],
    task_id: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Parent task ID (for subtask abandonment)"),
    ] = None,
    confirm: Annotated[
        str | None,
        typer.Option("--confirm", help="Confirm token from preview run"),
    ] = None,
    reason: Annotated[
        str | None,
        typer.Option("--reason", "-r", help="Reason for abandonment"),
    ] = None,
) -> None:
    """Abandon a task or subtask and roll back tracked code changes.

    For subtasks: Resets subtask status (single-pass).
    For tasks: Two-pass confirmation required.

    First run shows what will be destroyed and generates a confirm token.
    Second run with --confirm TOKEN executes the abandon.

    SAFE: Database is NOT restored. This uses append-only task metadata,
    preventing data loss when other tasks were created after this task's
    checkpoint was taken.

    \b
    Examples:
      st abandon 1.1 -t task-abc123              # Reset subtask status
      st abandon task-abc123                     # Preview blast radius
      st abandon task-abc123 --confirm a1b2c3d4  # Execute with preview token
    """
    from ..context import require_task_id

    client = STClient()

    if is_subtask_id(id):
        resolved_task_id = require_task_id(task_id)
        abandon_subtask(client, id, resolved_task_id, reason)
        output_success(f"Subtask {id} abandoned. Metadata updated.")
    else:
        abandon_task(client, id, confirm, reason)
        output_success(f"Task {id} abandoned. Status set to 'cancelled'; checkpoint metadata cleaned.")
