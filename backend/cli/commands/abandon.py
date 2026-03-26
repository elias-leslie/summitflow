"""Abandon command for st CLI.

Safe rollback for tasks and subtasks.
For tasks: Marks as abandoned, deletes git branches (NO DB restore).
For subtasks: Deletes git branch only.

Uses two-pass confirmation: first run shows blast radius and generates
a single-use token; second run with --confirm TOKEN executes.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import STClient
from ..output import output_success
from ._abandon_helpers import abandon_subtask, abandon_task, is_subtask_id

app = typer.Typer(help="Abandon task or subtask work and rollback")


@app.command(name="abandon")
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
    """Abandon a task or subtask and rollback code changes.

    For subtasks: Deletes git branch only (single-pass).
    For tasks: Two-pass confirmation required.

    First run shows what will be destroyed and generates a confirm token.
    Second run with --confirm TOKEN executes the abandon.

    SAFE: Database is NOT restored. This uses append-only task metadata,
    preventing data loss when other tasks were created after this task's
    checkpoint was taken.

    Examples:
        st abandon 1.1 -t task-abc123          # Abandon subtask (delete branch)
        st abandon task-abc123                  # Preview: show blast radius
        st abandon task-abc123 --confirm a1b2c3d4  # Execute with token from preview
    """
    from ..context import require_task_id

    client = STClient()

    if is_subtask_id(id):
        resolved_task_id = require_task_id(task_id)
        abandon_subtask(client, id, resolved_task_id, reason)
        output_success(f"Subtask {id} abandoned. Branch deleted.")
    else:
        abandon_task(client, id, confirm, reason)
        output_success(f"Task {id} abandoned. Branches deleted, status set to 'cancelled'.")
