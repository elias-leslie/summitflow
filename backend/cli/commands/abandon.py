"""Abandon command for st CLI.

Safe rollback for tasks and subtasks.
For tasks: Marks as abandoned, deletes git branches (NO DB restore).
For subtasks: Deletes git branch only.

IMPORTANT: This uses append-only task metadata. Tasks are NEVER deleted,
only marked as 'abandoned'. This prevents data loss when other tasks were
created after this task's checkpoint.
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

    if is_subtask_id(id):
        resolved_task_id = require_task_id(task_id)
        abandon_subtask(client, id, resolved_task_id, reason)
        output_success(f"Subtask {id} abandoned. Branch deleted.")
    else:
        abandon_task(client, id, force, discard, reason)
        output_success(f"Task {id} abandoned. Branches deleted, status set to 'abandoned'.")
