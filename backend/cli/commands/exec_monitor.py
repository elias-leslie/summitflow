"""Execution log command for the CLI.

Provides live monitoring of task execution via the events API.
Shows task ID, subtask status, tool calls with timestamps, and agent responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..context import require_task_id
from ..output import handle_api_error
from ..output_context import OutputContext
from .exec_monitor_follower import follow_events
from .exec_monitor_formatters import print_events, print_header


def _parse_iso_timestamp(value: Any) -> datetime | None:
    """Parse an ISO timestamp from API payloads."""
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _select_current_attempt(
    sessions: list[dict[str, Any]],
    agent_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, datetime | None]:
    """Keep only the current task attempt cluster for exec-log output.

    Priority:
    1. Any active sessions.
    2. Otherwise, sessions updated within a short window of the newest session.
    This keeps current refactor + feedback sessions together while hiding old retries.
    """
    if len(sessions) <= 1:
        attempt_start = min(
            (
                _parse_iso_timestamp(event.get("created_at"))
                for event in agent_events
            ),
            default=None,
        )
        return sessions, agent_events, 0, attempt_start

    active_sessions = [s for s in sessions if s.get("status") == "active"]
    if active_sessions:
        active_ids = {str(s.get("id")) for s in active_sessions if s.get("id")}
        first_active_index = next(
            (idx for idx, session in enumerate(sessions) if str(session.get("id")) in active_ids),
            len(sessions) - 1,
        )
        selected_sessions = sessions[first_active_index:]
    else:
        primary_slug = str(sessions[-1].get("agent_slug") or "")
        if len(sessions) >= 2:
            previous_slug = str(sessions[-2].get("agent_slug") or "")
            if previous_slug and previous_slug != primary_slug:
                primary_slug = previous_slug
        start_index = next(
            (
                idx
                for idx in range(len(sessions) - 1, -1, -1)
                if str(sessions[idx].get("agent_slug") or "") == primary_slug
            ),
            len(sessions) - 1,
        )
        selected_sessions = sessions[start_index:]

    selected_ids = {str(s.get("id")) for s in selected_sessions if s.get("id")}
    filtered_sessions = [s for s in sessions if str(s.get("id")) in selected_ids]
    filtered_events = [
        event
        for event in agent_events
        if str(event.get("session_id")) in selected_ids
    ]
    attempt_start = min(
        (
            _parse_iso_timestamp(event.get("created_at"))
            for event in filtered_events
        ),
        default=None,
    )
    hidden_count = max(len(sessions) - len(filtered_sessions), 0)
    return filtered_sessions, filtered_events, hidden_count, attempt_start


def _fetch_task_data(
    client: STClient,
    task_id: str,
    limit: int,
    debug: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Fetch task, subtasks, and events from the API."""
    task = client.get_task(task_id)
    project_id = task.get("project_id", "unknown")
    subtasks_data = client.get_subtasks(task_id)
    subtasks = subtasks_data.get("subtasks", [])
    events = client.get_events(project_id, task_id, limit=limit, include_debug=debug)
    agent_sessions = client.get_task_agent_sessions(task_id)
    agent_events = client.get_task_agent_events(task_id, page_size=min(max(limit, 20), 100))
    return task, subtasks, events, agent_sessions, agent_events


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
        task, subtasks, events, agent_sessions, agent_events = _fetch_task_data(client, task_id, limit, debug)
    except APIError as e:
        handle_api_error(e)
        return

    _display_events(
        ctx.obj,
        task,
        subtasks,
        events,
        agent_sessions,
        agent_events,
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
    agent_events: dict[str, Any],
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
    session_list = agent_sessions.get("sessions", []) if isinstance(agent_sessions, dict) else []
    agent_event_list = agent_events.get("events", []) if isinstance(agent_events, dict) else []
    session_list, agent_event_list, hidden_attempts, attempt_start = _select_current_attempt(
        session_list,
        agent_event_list,
    )
    filtered_agent_sessions = {**agent_sessions, "sessions": session_list} if isinstance(agent_sessions, dict) else agent_sessions
    events_list = events.get("events", []) if isinstance(events, dict) else events
    if attempt_start is not None:
        events_list = [
            event
            for event in events_list
            if (_parse_iso_timestamp(event.get("timestamp")) or attempt_start) >= attempt_start
        ]

    # Header
    print_header(out, task, subtasks, filtered_agent_sessions, debug, json_output, hidden_attempts=hidden_attempts)
    if agent_event_list and not json_output and not out.is_compact:
        print("Recent Agent Activity:")
    print_events(
        out,
        agent_event_list[-12:],
        debug,
        json_output,
        agent_event_mode=True,
    )

    # Initial events
    print_events(out, events_list, debug, json_output)

    if not follow:
        return

    # Follow mode - poll for new events
    last_event_id = events_list[-1].get("id") if events_list else None
    follow_events(out, task_id, project_id, status, last_event_id, client, debug, json_output)
