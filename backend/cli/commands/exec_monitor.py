"""Execution monitor command for the CLI.

Provides live monitoring of task execution via the events API.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..context import require_task_id
from ..output import handle_api_error, is_compact

app = typer.Typer(help="Monitor execution progress in real-time")


@app.callback(invoke_without_command=True)
def exec_monitor_default(
    ctx: typer.Context,
    task_id: Annotated[
        str | None,
        typer.Argument(help="Task ID to monitor (uses active context if not provided)"),
    ] = None,
    follow: Annotated[
        bool,
        typer.Option("-f", "--follow", help="Follow events in real-time (poll)"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("-n", "--limit", help="Maximum events to show"),
    ] = 50,
) -> None:
    """Monitor execution progress for a task.

    Shows recent events and optionally follows in real-time.

    Examples:
        st exec-monitor task-abc123
        st exec-monitor -f                  # Uses active context, follow mode
        st exec-monitor --limit 100         # Show more events
    """
    if ctx.invoked_subcommand is not None:
        return

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        # Get task info for context
        task = client.get_task(task_id)
        project_id = task.get("project_id", "unknown")

        # Get events from API
        events = client.get_events(project_id, task_id, limit=limit)
    except APIError as e:
        handle_api_error(e)
        return

    _display_events(task, events, follow, client, limit)


def _display_events(
    task: dict,
    events: list,
    follow: bool,
    client: STClient,
    limit: int,
) -> None:
    """Display events for a task."""
    import time

    task_id = task.get("id", "unknown")
    project_id = task.get("project_id", "unknown")
    title = task.get("title", "Unknown")[:50]
    status = task.get("status", "unknown")

    # Header
    if is_compact():
        print(f"EXEC:{task_id}|{status}|{title}")
    else:
        print(f"Task: {task_id}")
        print(f"Title: {title}")
        print(f"Status: {status}")
        print("-" * 60)

    # Initial events
    events_list = events.get("events", []) if isinstance(events, dict) else events
    _print_events(events_list)

    if not follow:
        return

    # Follow mode - poll for new events
    last_event_id = events_list[-1].get("id") if events_list else None
    print("\n[Following... Press Ctrl+C to stop]\n")

    try:
        while True:
            time.sleep(2)

            # Check task status
            try:
                task = client.get_task(task_id)
                new_status = task.get("status", "unknown")

                if new_status != status:
                    status = new_status
                    print(f"\n[Status changed: {status}]")

                if status in ("completed", "cancelled", "failed", "closed"):
                    print(f"\n[Task {status}]")
                    break

                # Get new events
                new_events = client.get_events(project_id, task_id, limit=10)
                events_list = (
                    new_events.get("events", [])
                    if isinstance(new_events, dict)
                    else new_events
                )

                if events_list:
                    # Filter to only new events
                    if last_event_id:
                        new_only = [
                            e for e in events_list if e.get("id") != last_event_id
                        ]
                        # Check if we have events newer than last
                        if new_only and events_list[0].get("id") != last_event_id:
                            _print_events(new_only)
                            last_event_id = events_list[0].get("id")
                    else:
                        last_event_id = events_list[0].get("id")
            except APIError:
                # Ignore transient errors in follow mode
                pass

    except KeyboardInterrupt:
        print("\n[Stopped]")


def _print_events(events: list) -> None:
    """Print a list of events."""
    for event in reversed(events):  # Show oldest first
        timestamp = event.get("timestamp", "")[:19]  # Truncate to seconds
        level = event.get("level", "info")[:4].upper()
        message = event.get("message", "")
        source = event.get("source", "")

        # Level colors for terminal
        level_prefix = {
            "DEBU": ".",
            "INFO": " ",
            "WARN": "!",
            "ERRO": "X",
        }.get(level, " ")

        if is_compact():
            # TOON format: timestamp|level|message
            print(f"{timestamp}|{level}|{message[:80]}")
        else:
            # Human-readable format
            source_str = f" [{source}]" if source else ""
            print(f"{level_prefix} {timestamp} {message}{source_str}")
