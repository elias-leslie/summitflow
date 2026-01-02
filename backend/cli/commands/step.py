"""Step commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import console, handle_api_error, output_json, output_success

app = typer.Typer(help="Step management commands")


@app.command("pass")
def pass_step(
    task_id: str,
    subtask_id: str,
    step_number: int,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Mark a step as passed.

    Examples:
        st step pass task-abc123 1.1 1
        st step pass task-abc123 1.1 2 --json
    """
    client = STClient()

    try:
        result = client.update_step(task_id, subtask_id, step_number, passes=True)
    except APIError as e:
        handle_api_error(e)
        return

    if json_output:
        output_json(result)
    else:
        output_success(f"Marked step {step_number} of subtask {subtask_id} as passed")


@app.command("create")
def create_steps(
    task_id: str,
    subtask_id: str,
    descriptions: Annotated[list[str], typer.Argument()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create steps for a subtask in batch.

    Pass multiple step descriptions as arguments.

    Examples:
        st step create task-abc123 1.1 "Step 1" "Step 2" "Step 3"
    """
    client = STClient()

    try:
        result = client.bulk_create_steps(task_id, subtask_id, descriptions)
    except APIError as e:
        handle_api_error(e)
        return

    if json_output:
        output_json(result)
    else:
        created = result.get("created", [])
        output_success(f"Created {len(created)} steps for subtask {subtask_id}")


@app.command("list")
def list_steps(
    task_id: str,
    subtask_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List steps for a subtask.

    Examples:
        st step list task-abc123 1.1
        st step list task-abc123 1.1 --json
    """
    client = STClient()

    try:
        steps = client.get_steps(task_id, subtask_id)
    except APIError as e:
        handle_api_error(e)
        return

    if json_output:
        output_json(steps)
        return

    if not steps:
        console.print("[dim]No steps found.[/dim]")
        return

    from rich.table import Table

    table = Table(title=f"Steps for {subtask_id}", show_header=True, header_style="bold")
    table.add_column("#", width=3, justify="center")
    table.add_column("", width=3, justify="center")
    table.add_column("Description")

    for step in steps:
        step_num = step.get("step_number", 0)
        passes = step.get("passes", False)
        desc = step.get("description", "")
        icon = "[green]✓[/]" if passes else "[dim]○[/]"

        table.add_row(str(step_num), icon, desc)

    console.print(table)
