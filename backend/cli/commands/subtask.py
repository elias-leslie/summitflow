"""Subtask commands for the CLI."""

from __future__ import annotations

from typing import Annotated, Any, cast

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error, output_success

# Re-export for backward compatibility
from .subtask_citations import log_citations_cmd
from .subtask_validation import is_step_resolved, validate_steps_input

app = typer.Typer(help="Subtask management commands")


@app.command("create")
def create_subtask(
    subtask_id: str,
    description: Annotated[str, typer.Option("-d", "--description")],
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
    phase: Annotated[str, typer.Option("--phase")] = "implementation",
    steps: Annotated[list[str] | None, typer.Option("--step")] = None,
    steps_json: Annotated[
        str | None,
        typer.Option("--steps-json", help="JSON array of step objects"),
    ] = None,
) -> None:
    """Create a subtask for a task. Uses active context if no --task given.

    Use --steps-json for structured step objects,
    or --step for simple descriptions.
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    final_steps = validate_steps_input(steps_json, steps)

    client = STClient()
    try:
        client.create_subtask(
            task_id=task_id,
            subtask_id=subtask_id,
            description=description,
            phase=phase,
            steps=cast(list[str | dict[str, Any]] | None, final_steps),
        )
    except APIError as e:
        handle_api_error(e)
        return

    output_success(subtask_id)


@app.command("pass")
def pass_subtask(
    subtask_id: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Mark a subtask as passed. All steps must be complete (enforced by DB trigger)."""
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    _check_incomplete_steps(client, task_id, subtask_id)

    try:
        client.update_subtask(task_id, subtask_id, passes=True)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(subtask_id)


def _get_incomplete_steps(steps: list[dict[str, Any]]) -> list[int]:
    """Return step numbers that are not yet resolved."""
    step_passes_map = {s["step_number"]: s.get("passes", False) for s in steps}
    return [s["step_number"] for s in steps if not is_step_resolved(s, step_passes_map)]


def _check_incomplete_steps(client: STClient, task_id: str, subtask_id: str) -> None:
    """Raise typer.Exit(1) if the subtask has incomplete steps."""
    try:
        result = client.get_subtasks(task_id, include_steps=True)
    except APIError:
        return  # Let API handle errors

    subtasks = result.get("subtasks", [])
    target = next((s for s in subtasks if s.get("subtask_id") == subtask_id), None)
    if not target:
        return

    steps = target.get("steps_from_table", [])
    if not steps:
        return

    incomplete = _get_incomplete_steps(steps)
    if incomplete:
        output_error(f"INCOMPLETE:{subtask_id}|steps:{','.join(map(str, incomplete))}")
        raise typer.Exit(1)


@app.command("delete")
def delete_subtask(
    subtask_id: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Delete a subtask and all its steps. Uses active context if no --task given."""
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
    typer.echo("  st context <task-id>    - Shows all subtasks with steps", err=True)
    raise typer.Exit(1)


@app.command("show", hidden=True)
def show_removed() -> None:
    """Removed: use st context --subtask instead."""
    typer.echo("Command 'subtask show' has been removed.\n", err=True)
    typer.echo("Use instead:", err=True)
    typer.echo("  st context <task-id> --subtask X.Y    - Subtask-scoped context", err=True)
    raise typer.Exit(1)
