"""Subtask commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error, output_success

# Re-export for backward compatibility
from .subtask_citations import log_citations_cmd

app = typer.Typer(help="Subtask management commands")


@app.command("create")
def create_subtask(
    subtask_id: str,
    description: Annotated[str, typer.Option("-d", "--description")],
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
    phase: Annotated[str, typer.Option("--phase")] = "implementation",
) -> None:
    """Create a subtask for a task. Uses active context if no --task given."""
    from ..context import require_task_id

    task_id = require_task_id(task_id)

    client = STClient()
    try:
        client.create_subtask(
            task_id=task_id,
            subtask_id=subtask_id,
            description=description,
            phase=phase,
        )
    except APIError as e:
        handle_api_error(e)
        return

    output_success(subtask_id)


@app.command("pass")
def pass_subtask(
    subtask_id: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
    citations: Annotated[
        list[str] | None,
        typer.Option("--citation", help="Inline memory citations for this pass"),
    ] = None,
    acknowledge_none: Annotated[
        bool,
        typer.Option("--none", help="Acknowledge that no memories were needed"),
    ] = False,
) -> None:
    """Mark a subtask as passed."""
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    if citations and acknowledge_none:
        output_error("Use either --citation or --none, not both.")
        raise typer.Exit(1)

    try:
        if citations:
            client.log_citations(task_id, subtask_id, citations)
        elif acknowledge_none:
            client.acknowledge_no_citations(task_id, subtask_id)
    except APIError as e:
        handle_api_error(e)
        return

    try:
        client.update_subtask(task_id, subtask_id, passes=True)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(subtask_id)


@app.command("delete")
def delete_subtask(
    subtask_id: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Delete a subtask. Uses active context if no --task given."""
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.delete_subtask(task_id, subtask_id)
    except APIError as e:
        handle_api_error(e)
        return

    print(f"DEL {subtask_id}")


# Register citations command
app.command("citations")(log_citations_cmd)


# Error stubs for removed commands - provide helpful redirects
@app.command("list", hidden=True)
def list_removed() -> None:
    """Removed: use st context instead."""
    typer.echo("Command 'subtask list' has been removed.\n", err=True)
    typer.echo("Use instead:", err=True)
    typer.echo("  st context <task-id>    - Shows all subtasks", err=True)
    raise typer.Exit(1)


@app.command("show", hidden=True)
def show_removed() -> None:
    """Removed: use st context --subtask instead."""
    typer.echo("Command 'subtask show' has been removed.\n", err=True)
    typer.echo("Use instead:", err=True)
    typer.echo("  st context <task-id> --subtask X.Y    - Subtask-scoped context", err=True)
    raise typer.Exit(1)
