"""Session events command - View Agent Hub session events for observability.

Supports both session ID and task ID lookups.
Task ID lookup uses the SummitFlow observability API which automatically
resolves linked Agent Hub sessions.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..context import require_task_id
from ..output import output_json
from .session_events_client import get_session_events, get_task_events
from .session_events_follow import follow_session_events, follow_task_events
from .session_events_formatter import display_events

# Messages
MSG_NO_TASK_EVENTS = "No agent events found for task {task_id}."
MSG_NO_SESSIONS_LINKED = "No Agent Hub sessions linked to this task yet."
MSG_NO_SESSION_EVENTS = "No events found for this session."

# Help strings for long option descriptions
_HELP_TASK = "Task ID (auto-resolves linked Agent Hub sessions)"
_HELP_EVENT_TYPE = "Filter by event type (tool_use, tool_result, user_message, assistant_message, thinking, memory_inject, error)"

app = typer.Typer(help="Agent Hub session events (observability)")


def _handle_task_events(
    task_id: str, event_type: str | None, turn: int | None,
    follow: bool, page: int, page_size: int, raw: bool, verbose: bool,
) -> None:
    """Handle the task-based event lookup path."""
    if follow:
        follow_task_events(task_id, event_type, verbose, page_size)
        return
    result = get_task_events(task_id, event_type, turn, page, page_size)
    if raw:
        output_json(result)
        return
    events = result.get("events", [])
    total = result.get("total", 0)
    max_turn = result.get("max_turn", 0)
    session_ids = result.get("session_ids", [])
    if not events:
        typer.echo(MSG_NO_TASK_EVENTS.format(task_id=task_id))
        if not session_ids:
            typer.echo(MSG_NO_SESSIONS_LINKED)
        return
    display_events(events, total, max_turn, f"Task: {task_id}", event_type, turn, page, verbose, session_ids=session_ids)


def _handle_session_events(
    session_id: str, event_type: str | None, turn: int | None,
    follow: bool, page: int, page_size: int, raw: bool, verbose: bool,
) -> None:
    """Handle the session-based event lookup path."""
    if follow:
        follow_session_events(session_id, event_type, verbose, page_size)
        return
    result = get_session_events(session_id, event_type, turn, page, page_size)
    if raw:
        output_json(result)
        return
    events = result.get("events", [])
    total = result.get("total", 0)
    max_turn = result.get("max_turn", 0)
    if not events:
        typer.echo(MSG_NO_SESSION_EVENTS)
        return
    display_events(events, total, max_turn, f"Session: {session_id}", event_type, turn, page, verbose)


@app.callback(invoke_without_command=True)
def show_events(
    ctx: typer.Context,
    session_id: Annotated[str | None, typer.Argument(help="Session ID to view")] = None,
    task: Annotated[str | None, typer.Option("--task", "-T", help=_HELP_TASK)] = None,
    event_type: Annotated[str | None, typer.Option("-t", "--type", help=_HELP_EVENT_TYPE)] = None,
    turn: Annotated[int | None, typer.Option("--turn", help="Filter by turn number")] = None,
    follow: Annotated[bool, typer.Option("-f", "--follow", help="Follow events in real-time (poll every 2s)")] = False,
    page: Annotated[int, typer.Option("--page", help="Page number")] = 1,
    page_size: Annotated[int, typer.Option("--page-size", "-n", help="Events per page")] = 50,
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show full content without truncation")] = False,
) -> None:
    """View Agent Hub session events for full observability.

    Shows tool calls, messages, thinking blocks, memory events, and errors.
    Use --task to auto-resolve sessions linked to a SummitFlow task.
    Use -f to follow events in real-time during autonomous execution.
    """
    if ctx.invoked_subcommand is not None:
        return
    if task:
        task_id = require_task_id(task)
        _handle_task_events(task_id, event_type, turn, follow, page, page_size, raw, verbose)
        return
    if not session_id:
        typer.echo(ctx.get_help())
        return
    _handle_session_events(session_id, event_type, turn, follow, page, page_size, raw, verbose)
