"""Autonomous execution commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import console, output_error, output_json, output_success

app = typer.Typer(help="Autonomous execution management")


def _handle_api_error(e: APIError) -> None:
    """Handle API error and exit."""
    output_error(e.detail)
    raise typer.Exit(1)


@app.command()
def enable(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Enable autonomous execution for the project.

    Examples:
        st autonomous enable
    """
    client = STClient()

    try:
        result = client.update_autonomous_settings(enabled=True)
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        output_json(result)
    else:
        output_success("Autonomous execution enabled")


@app.command()
def disable(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Disable autonomous execution for the project.

    Examples:
        st autonomous disable
    """
    client = STClient()

    try:
        result = client.update_autonomous_settings(enabled=False)
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        output_json(result)
    else:
        output_success("Autonomous execution disabled")


@app.command()
def status(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show autonomous execution status and metrics.

    Examples:
        st autonomous status
        st autonomous status --json
    """
    client = STClient()

    try:
        settings = client.get_autonomous_settings()
        metrics = client.get_autonomous_status()
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        output_json({"settings": settings, "metrics": metrics})
        return

    # Display settings
    enabled = settings.get("enabled", False)
    enabled_str = "[green]Enabled[/]" if enabled else "[red]Disabled[/]"
    freq = settings.get("frequency_minutes", 30)
    auto_merge = settings.get("auto_merge_tiers", [])
    task_types = settings.get("task_types", [])

    console.print("\n[bold]Autonomous Execution[/bold]")
    console.print(f"  Status: {enabled_str}")
    console.print(f"  Frequency: every {freq} minutes")
    console.print(f"  Auto-merge tiers: {auto_merge or 'none'}")
    console.print(f"  Task types: {', '.join(task_types) or 'all'}")

    # Display metrics
    total_exec = metrics.get("total_executions", 0)
    successful = metrics.get("successful_executions", 0)
    failed = metrics.get("failed_executions", 0)
    pending_review = metrics.get("pending_review", 0)
    next_pickup = metrics.get("next_pickup_time")

    console.print("\n[bold]Metrics[/bold]")
    console.print(f"  Total executions: {total_exec}")
    console.print(f"  Successful: [green]{successful}[/]")
    console.print(f"  Failed: [red]{failed}[/]")
    console.print(f"  Pending review: [yellow]{pending_review}[/]")
    if next_pickup:
        console.print(f"  Next pickup: {next_pickup}")

    # Recent activity
    recent = metrics.get("recent_activity", [])
    if recent:
        console.print("\n[bold]Recent Activity[/bold]")
        for activity in recent[:5]:
            task_id = activity.get("task_id", "")
            action = activity.get("action", "")
            timestamp = activity.get("timestamp", "")[:19]  # Trim microseconds
            console.print(f"  {timestamp}: {action} - {task_id}")
