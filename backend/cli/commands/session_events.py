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

app = typer.Typer(help="Agent Hub session events (observability)")


@app.callback(invoke_without_command=True)
def show_events(
    ctx: typer.Context,
    session_id: Annotated[str | None, typer.Argument(help="Session ID to view")] = None,
    task: Annotated[
        str | None,
        typer.Option("--task", "-T", help="Task ID (auto-resolves linked Agent Hub sessions)"),
    ] = None,
    event_type: Annotated[
        str | None,
        typer.Option(
            "-t",
            "--type",
            help="Filter by event type (tool_use, tool_result, user_message, assistant_message, thinking, memory_inject, error)",
        ),
    ] = None,
    turn: Annotated[int | None, typer.Option("--turn", help="Filter by turn number")] = None,
    follow: Annotated[
        bool, typer.Option("-f", "--follow", help="Follow events in real-time (poll every 2s)")
    ] = False,
    page: Annotated[int, typer.Option("--page", help="Page number")] = 1,
    page_size: Annotated[int, typer.Option("--page-size", "-n", help="Events per page")] = 50,
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show full content without truncation")
    ] = False,
) -> None:
    """View Agent Hub session events for full observability.

    Shows the complete execution timeline including tool calls,
    messages, thinking blocks, memory events, and errors.

    Use --task to auto-resolve sessions linked to a SummitFlow task.
    Use -f to follow events in real-time during autonomous execution.

    Examples:
        st session-events --task task-abc123          # By task ID
        st session-events --task task-abc123 -f       # Follow mode
        st session-events --task task-abc123 -t tool_use  # Tool calls only
        st session-events abc123                      # By session ID
        st session-events abc123 -f                   # Follow session
        st session-events abc123 --turn 2 -v          # Turn 2, verbose
    """
    if ctx.invoked_subcommand is not None:
        return

    if task:
        task_id = require_task_id(task)

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
            typer.echo(f"No agent events found for task {task_id}.")
            if not session_ids:
                typer.echo("No Agent Hub sessions linked to this task yet.")
            return

        display_events(
            events, total, max_turn,
            f"Task: {task_id}",
            event_type, turn, page, verbose,
            session_ids=session_ids,
        )
        return

    if not session_id:
        typer.echo(ctx.get_help())
        return

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
        typer.echo("No events found for this session.")
        return

    display_events(
        events, total, max_turn,
        f"Session: {session_id}",
        event_type, turn, page, verbose,
    )
