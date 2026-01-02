"""Subtask commands for the CLI."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..output import console, output_error, output_json, output_success

app = typer.Typer(help="Subtask management commands")


def _handle_api_error(e: APIError) -> None:
    """Handle API error and exit."""
    output_error(e.detail)
    raise typer.Exit(1)


def _output_subtask(subtask: dict[str, Any], json_mode: bool = False) -> None:
    """Output a single subtask with step details."""
    if json_mode:
        output_json(subtask)
        return

    from rich.panel import Panel

    subtask_id = subtask.get("subtask_id", subtask.get("id", ""))
    phase = subtask.get("phase", "")
    description = subtask.get("description", "")
    passes = subtask.get("passes", False)
    step_summary = subtask.get("step_summary", {})

    status_icon = "[green]✓[/]" if passes else "[yellow]○[/]"
    title = f"{status_icon} Subtask {subtask_id}"
    if phase:
        title += f" [{phase}]"

    content_lines = [f"[bold]{description}[/bold]"]

    if step_summary:
        total = step_summary.get("total", 0)
        completed = step_summary.get("completed", 0)
        pct = step_summary.get("progress_percent", 0)
        content_lines.append(f"\nProgress: {completed}/{total} steps ({pct:.0f}%)")

    # Show steps if available
    steps = subtask.get("steps_from_table", [])
    if steps:
        content_lines.append("\n[bold]Steps:[/bold]")
        for step in steps:
            step_num = step.get("step_number", 0)
            step_desc = step.get("description", "")
            step_passes = step.get("passes", False)
            icon = "[green]✓[/]" if step_passes else "[dim]○[/dim]"
            content_lines.append(f"  {icon} {step_num}. {step_desc}")

    panel = Panel(
        "\n".join(content_lines),
        title=title,
        border_style="green" if passes else "yellow",
    )
    console.print(panel)


def _output_subtask_list(
    subtasks: list[dict[str, Any]],
    summary: dict[str, Any],
    json_mode: bool = False,
) -> None:
    """Output subtask list with progress table."""
    if json_mode:
        output_json({"subtasks": subtasks, "summary": summary})
        return

    if not subtasks:
        console.print("[dim]No subtasks found.[/dim]")
        return

    from rich.table import Table

    # Summary header
    total = summary.get("total", len(subtasks))
    completed = summary.get("completed", 0)
    pct = summary.get("progress_percent", 0.0)
    next_id = summary.get("next_subtask_id", "")

    console.print(f"\n[bold]Subtasks:[/bold] {completed}/{total} completed ({pct:.0f}%)")
    if next_id:
        console.print(f"[dim]Next: {next_id}[/dim]")
    console.print()

    # Table
    table = Table(show_header=True, header_style="bold")
    table.add_column("", width=3, justify="center")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Phase", style="dim", no_wrap=True)
    table.add_column("Description")
    table.add_column("Steps", justify="center", no_wrap=True)
    table.add_column("Progress", no_wrap=True)

    for subtask in subtasks:
        passes = subtask.get("passes", False)
        icon = "[green]✓[/]" if passes else "[dim]○[/]"
        subtask_id = subtask.get("subtask_id", "")
        phase = subtask.get("phase", "")[:10]
        desc = subtask.get("description", "")[:50]
        if len(subtask.get("description", "")) > 50:
            desc += "..."

        step_summary = subtask.get("step_summary", {})
        step_total = step_summary.get("total", 0)
        step_completed = step_summary.get("completed", 0)
        step_pct = step_summary.get("progress_percent", 0.0)

        steps_text = f"{step_completed}/{step_total}" if step_total else "-"

        # Progress bar using unicode
        if step_total:
            filled = int(step_pct / 10)
            bar = "[green]" + "█" * filled + "[/][dim]" + "░" * (10 - filled) + "[/]"
        else:
            bar = "[dim]░░░░░░░░░░[/]"

        table.add_row(icon, subtask_id, phase, desc, steps_text, bar)

    console.print(table)


@app.command("list")
def list_subtasks(
    task_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List subtasks for a task with progress.

    Examples:
        st subtask list task-abc123
        st subtask list task-abc123 --json
    """
    client = STClient()

    try:
        result = client.get_subtasks(task_id, include_steps=True)
    except APIError as e:
        _handle_api_error(e)
        return

    subtasks = result.get("subtasks", [])
    summary = result.get("summary", {})

    _output_subtask_list(subtasks, summary, json_output)


@app.command("show")
def show_subtask(
    task_id: str,
    subtask_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show details of a specific subtask.

    Examples:
        st subtask show task-abc123 1.1
        st subtask show task-abc123 1.1 --json
    """
    client = STClient()

    try:
        result = client.get_subtasks(task_id, include_steps=True)
    except APIError as e:
        _handle_api_error(e)
        return

    subtasks = result.get("subtasks", [])
    target = None
    for s in subtasks:
        if s.get("subtask_id") == subtask_id:
            target = s
            break

    if target is None:
        output_error(f"Subtask {subtask_id} not found for task {task_id}")
        raise typer.Exit(1)

    _output_subtask(target, json_output)


@app.command("create")
def create_subtask(
    task_id: str,
    subtask_id: str,
    description: Annotated[str, typer.Option("-d", "--description")],
    phase: Annotated[str, typer.Option("--phase")] = "implementation",
    steps: Annotated[list[str] | None, typer.Option("--step")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create a subtask for a task.

    Examples:
        st subtask create task-abc123 1.1 -d "Add component" --phase backend
        st subtask create task-abc123 1.1 -d "Add component" --step "Step 1" --step "Step 2"
    """
    client = STClient()

    try:
        result = client.create_subtask(
            task_id=task_id,
            subtask_id=subtask_id,
            description=description,
            phase=phase,
            steps=steps,
        )
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        output_json(result)
    else:
        output_success(f"Created subtask {subtask_id} for task {task_id}")


@app.command("pass")
def pass_subtask(
    task_id: str,
    subtask_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Mark a subtask as passed.

    Examples:
        st subtask pass task-abc123 1.1
    """
    client = STClient()

    try:
        result = client.update_subtask(task_id, subtask_id, passes=True)
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        output_json(result)
    else:
        output_success(f"Marked subtask {subtask_id} as passed")
