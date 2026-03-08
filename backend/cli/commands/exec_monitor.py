"""Execution log command for the CLI.

Provides live monitoring of task execution via the events API.
Shows task ID, subtask status, tool calls with timestamps, and agent responses.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..context import require_task_id
from ..output import handle_api_error
from ..output_context import OutputContext
from .exec_monitor_follower import follow_events
from .exec_monitor_formatters import print_events, print_header


def _fetch_task_data(
    client: STClient,
    task_id: str,
    limit: int,
    debug: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Fetch task, subtasks, and events from the API."""
    task = client.get_task(task_id)
    project_id = task.get("project_id", "unknown")
    subtasks_data = client.get_subtasks(task_id)
    subtasks = subtasks_data.get("subtasks", [])
    events = client.get_events(project_id, task_id, limit=limit, include_debug=debug)
    agent_sessions = client.get_task_agent_sessions(task_id)
    return task, subtasks, events, agent_sessions


def exec_log_command(
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
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Include debug-level events with timing and attributes"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON (one event per line, for agent parsing)"),
    ] = False,
) -> None:
    """View execution progress for a task.

    Shows task ID, subtask status, tool calls with timestamps, and agent responses.
    Supports follow mode for real-time monitoring.

    Examples:
        st exec-log task-abc123
        st exec-log task-abc123 -f      # Follow mode
        st exec-log -n 100 task-abc123  # Show more events
        st exec-log -f                  # Uses active context, follow mode
        st exec-log --debug             # Include debug events with timing
        st exec-log --json              # JSON output for agent parsing
    """
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        task, subtasks, events, agent_sessions = _fetch_task_data(client, task_id, limit, debug)
    except APIError as e:
        handle_api_error(e)
        return

    _display_events(
        ctx.obj,
        task,
        subtasks,
        events,
        agent_sessions,
        follow,
        client,
        limit,
        debug,
        json_output,
    )

def _display_events(
    out: OutputContext,
    task: dict[str, Any],
    subtasks: list[dict[str, Any]],
    events: dict[str, Any],
    agent_sessions: dict[str, Any],
    follow: bool,
    client: STClient,
    limit: int,
    debug: bool = False,
    json_output: bool = False,
) -> None:
    """Display events for a task."""
    task_id = task.get("id", "unknown")
    project_id = task.get("project_id", "unknown")
    status = task.get("status", "unknown")

    # Header
    print_header(out, task, subtasks, agent_sessions, debug, json_output)

    # Initial events
    events_list = events.get("events", []) if isinstance(events, dict) else events
    print_events(out, events_list, debug, json_output)

    if not follow:
        return

    # Follow mode - poll for new events
    last_event_id = events_list[-1].get("id") if events_list else None
    follow_events(out, task_id, project_id, status, last_event_id, client, debug, json_output)
