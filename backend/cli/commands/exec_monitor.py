"""Execution monitor command for the CLI.

Provides live monitoring of task execution via the events API.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..context import require_task_id
from ..output import handle_api_error, is_compact


def exec_monitor_command(
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
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Include debug-level events with timing and attributes"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON (one event per line, for agent parsing)"),
    ] = False,
) -> None:
    """Monitor execution progress for a task.

    Shows recent events and optionally follows in real-time.

    Examples:
        st exec-monitor task-abc123
        st exec-monitor task-abc123 -f      # Follow mode
        st exec-monitor -n 100 task-abc123  # Show more events
        st exec-monitor -f                  # Uses active context, follow mode
        st exec-monitor --debug             # Include debug events with timing
        st exec-monitor --json              # JSON output for agent parsing
    """
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        # Get task info for context
        task = client.get_task(task_id)
        project_id = task.get("project_id", "unknown")

        # Get events from API
        events = client.get_events(project_id, task_id, limit=limit, include_debug=debug)
    except APIError as e:
        handle_api_error(e)
        return

    _display_events(task, events, follow, client, limit, debug, json_output)


def _display_events(
    task: dict[str, Any],
    events: dict[str, Any],
    follow: bool,
    client: STClient,
    limit: int,
    debug: bool = False,
    json_output: bool = False,
) -> None:
    """Display events for a task."""
    import json
    import time

    task_id = task.get("id", "unknown")
    project_id = task.get("project_id", "unknown")
    title = task.get("title", "Unknown")[:50]
    status = task.get("status", "unknown")

    # Header (skip for JSON output)
    if not json_output:
        if is_compact():
            print(f"EXEC:{task_id}|{status}|{title}")
        else:
            print(f"Task: {task_id}")
            print(f"Title: {title}")
            print(f"Status: {status}")
            if debug:
                print("Mode: debug (showing all visibility levels)")
            print("-" * 60)

    # Initial events
    events_list = events.get("events", []) if isinstance(events, dict) else events
    _print_events(events_list, debug, json_output)

    if not follow:
        return

    # Follow mode - poll for new events
    last_event_id = events_list[-1].get("id") if events_list else None
    if not json_output:
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
                    if json_output:
                        print(json.dumps({"type": "status_change", "status": status}))
                    else:
                        print(f"\n[Status changed: {status}]")

                if status in ("completed", "cancelled", "failed", "closed"):
                    if json_output:
                        print(json.dumps({"type": "task_ended", "status": status}))
                    else:
                        print(f"\n[Task {status}]")
                    break

                # Get new events
                new_events = client.get_events(project_id, task_id, limit=10, include_debug=debug)
                events_list = (
                    new_events.get("events", []) if isinstance(new_events, dict) else new_events
                )

                if events_list:
                    # Filter to only new events
                    if last_event_id:
                        new_only = [e for e in events_list if e.get("id") != last_event_id]
                        # Check if we have events newer than last
                        if new_only and events_list[0].get("id") != last_event_id:
                            _print_events(new_only, debug, json_output)
                            last_event_id = events_list[0].get("id")
                    else:
                        last_event_id = events_list[0].get("id")
            except APIError:
                # Ignore transient errors in follow mode
                pass

    except KeyboardInterrupt:
        if not json_output:
            print("\n[Stopped]")


def _print_events(events: list[Any], debug: bool = False, json_output: bool = False) -> None:
    """Print a list of events."""
    import json

    for event in reversed(events):  # Show oldest first
        if json_output:
            # One JSON object per line for agent parsing
            print(json.dumps(event))
            continue

        timestamp = event.get("timestamp", "")[:19]  # Truncate to seconds
        level = event.get("level", "info")[:4].upper()
        message = event.get("message", "")
        source = event.get("source", "")
        visibility = event.get("visibility", "user")
        attributes = event.get("attributes", {})

        # Level colors for terminal
        level_prefix = {
            "DEBU": ".",
            "INFO": " ",
            "WARN": "!",
            "ERRO": "X",
        }.get(level, " ")

        # Debug visibility indicator
        vis_indicator = ""
        if debug and visibility == "debug":
            vis_indicator = "[D] "
        elif debug and visibility == "internal":
            vis_indicator = "[I] "

        if is_compact():
            # TOON format: timestamp|level|message
            print(f"{timestamp}|{level}|{vis_indicator}{message[:80]}")
        else:
            # Human-readable format
            source_str = f" [{source}]" if source else ""
            print(f"{level_prefix} {timestamp} {vis_indicator}{message}{source_str}")

            # Show attributes in debug mode
            if debug and attributes:
                elapsed = attributes.get("elapsed_ms")
                if elapsed is not None:
                    print(f"    elapsed: {elapsed:.1f}ms")
                for key, value in attributes.items():
                    if key not in ("elapsed_ms", "level", "message", "source"):
                        if isinstance(value, str) and len(value) > 60:
                            value = value[:60] + "..."
                        print(f"    {key}: {value}")
