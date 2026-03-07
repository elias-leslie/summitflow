"""Done command for st CLI.

Checkpoint-aware completion for tasks and subtasks.
Merges git branches and cleans up DB snapshots.

Smart default: auto-verifies steps, auto-closes subtasks, stash-merge-pop.
Use --strict for old gate-check-only behavior.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import STClient
from ..output import output_success
from .done_subtask import complete_subtask
from .done_task import complete_task
from .done_validators import is_subtask_id

app = typer.Typer(help="Complete task or subtask work")


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


def _handle_task_completion(
    client: STClient,
    id: str,
    message: str | None,
    strict: bool,
    admin: bool,
) -> None:
    """Handle task completion."""
    result = complete_task(client, id, message, strict=strict, admin=admin)
    if result.get("merged"):
        base_branch = result.get("base_branch", "main")
        output_success(f"Task {id} completed. Checkpoint removed.")
        typer.echo(f"  Merged to: {base_branch}")
    else:
        output_success(f"Task {id} completed without checkpoint merge.")
    typer.echo("💡 Any feedback? st feedback report <component> \"title\" --type friction|idea|improvement|praise", err=True)


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
) -> None:
    """Complete a task or subtask.

    Smart mode (default): auto-verifies steps, auto-closes subtasks, stashes dirty main.
    Strict mode (--strict): fails if gates not pre-passed or main dirty.
    """
    client = STClient()

    if is_subtask_id(id):
        _handle_subtask_completion(client, id, task_id, message)
    else:
        _handle_task_completion(client, id, message, strict, admin)
