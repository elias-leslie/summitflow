"""Session events command - View Agent Hub session events for observability.

Supports both session ID and task ID lookups.
Task ID lookup uses the SummitFlow observability API which automatically
resolves linked Agent Hub sessions.
"""

from __future__ import annotations

import json
import time
from typing import Annotated, Any, cast

import httpx
import typer

from ..client import APIError, STClient
from ..config import get_agent_hub_url
from ..context import require_task_id
from ..output import handle_api_error, output_error, output_json

app = typer.Typer(help="Agent Hub session events (observability)")


def _load_credentials() -> tuple[str, str, str]:
    """Load credentials from ~/.env.local."""
    from pathlib import Path

    env_file = Path.home() / ".env.local"
    if not env_file.exists():
        output_error("~/.env.local not found")
        raise typer.Exit(1)

    creds: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            creds[key.strip()] = val.strip()

    client_id = creds.get("SUMMITFLOW_CLIENT_ID") or creds.get("CONSULT_CLIENT_ID")
    client_secret = creds.get("SUMMITFLOW_CLIENT_SECRET") or creds.get("CONSULT_CLIENT_SECRET")
    request_source = creds.get("SUMMITFLOW_REQUEST_SOURCE", "st-session-events")

    if not client_id or not client_secret:
        output_error(
            "Missing CONSULT_CLIENT_ID/SECRET or SUMMITFLOW_CLIENT_ID/SECRET in ~/.env.local"
        )
        raise typer.Exit(1)

    return client_id, client_secret, request_source


def _get_session_events(
    session_id: str,
    event_type: str | None = None,
    turn: int | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    """Fetch session events from Agent Hub directly by session ID."""
    client_id, client_secret, request_source = _load_credentials()

    headers = {
        "X-Client-Id": client_id,
        "X-Client-Secret": client_secret,
        "X-Request-Source": request_source,
    }

    params: dict[str, Any] = {
        "page": page,
        "page_size": page_size,
    }
    if event_type:
        params["event_type"] = event_type
    if turn is not None:
        params["turn"] = turn

    agent_hub_url = get_agent_hub_url()
    url = f"{agent_hub_url}/api/sessions/{session_id}/events"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers, params=params)

            if response.status_code >= 400:
                try:
                    detail = response.json().get("detail", response.text)
                except Exception:
                    detail = response.text
                output_error(f"API error ({response.status_code}): {detail}")
                raise typer.Exit(1) from None

            return cast(dict[str, Any], response.json())
    except httpx.ConnectError:
        output_error(f"Cannot connect to Agent Hub at {agent_hub_url}")
        raise typer.Exit(1) from None
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Request failed: {e}")
        raise typer.Exit(1) from None


def _get_task_events(
    task_id: str,
    event_type: str | None = None,
    turn: int | None = None,
    page: int = 1,
    page_size: int = 500,
) -> dict[str, Any]:
    """Fetch agent events for a task via SummitFlow observability API."""
    client = STClient()
    try:
        return client.get_task_agent_events(
            task_id,
            event_type=event_type,
            turn=turn,
            page=page,
            page_size=page_size,
        )
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None


def _format_event(event: dict[str, Any], verbose: bool = False) -> str:
    """Format a single event for display."""
    event_type = event.get("event_type", "unknown")
    turn = event.get("turn", 0)
    seq = event.get("sequence", 0)
    content = event.get("content") or ""
    tool_name = event.get("tool_name")
    tokens = event.get("tokens")
    model = event.get("model_used")

    type_colors = {
        "user_message": "\033[36m",
        "assistant_message": "\033[32m",
        "system_message": "\033[33m",
        "thinking": "\033[35m",
        "tool_use": "\033[34m",
        "tool_result": "\033[34m",
        "memory_inject": "\033[90m",
        "memory_cite": "\033[90m",
        "error": "\033[31m",
    }
    reset = "\033[0m"
    color = type_colors.get(event_type, "")

    header = f"{color}[{turn}.{seq}] {event_type}{reset}"
    if tool_name:
        header += f" ({tool_name})"
    if tokens:
        header += f" [{tokens} tokens]"
    if model and verbose:
        header += f" [{model}]"

    if event_type in ("tool_use", "tool_result"):
        tool_input = event.get("tool_input")
        tool_output = event.get("tool_output")
        if event_type == "tool_use" and tool_input:
            input_str = json.dumps(tool_input)
            if len(input_str) > 100 and not verbose:
                input_str = input_str[:100] + "..."
            content = input_str
        elif event_type == "tool_result" and tool_output:
            output_str = json.dumps(tool_output)
            if len(output_str) > 100 and not verbose:
                output_str = output_str[:100] + "..."
            content = output_str

    if content and len(content) > 200 and not verbose:
        content = content[:200] + "..."

    if content:
        indented = "  " + content.replace("\n", "\n  ")
        return f"{header}\n{indented}"
    return header


def _display_events(
    events: list[dict[str, Any]],
    total: int,
    max_turn: int,
    label: str,
    event_type: str | None,
    turn_filter: int | None,
    page: int,
    verbose: bool,
    session_ids: list[str] | None = None,
) -> None:
    """Display events with header and footer."""
    typer.echo(f"\n {label}")
    if session_ids:
        typer.echo(f" Sessions: {', '.join(session_ids[:5])}")
    typer.echo(f" Events: {total} | Max turn: {max_turn}")
    if event_type:
        typer.echo(f" Filter: type={event_type}")
    if turn_filter is not None:
        typer.echo(f" Filter: turn={turn_filter}")
    typer.echo("-" * 60)

    for event in events:
        typer.echo(_format_event(event, verbose))
        typer.echo()

    if len(events) < total:
        typer.echo(f"Showing {len(events)} of {total} events (page {page})")


def _follow_task_events(
    task_id: str,
    event_type: str | None,
    verbose: bool,
    page_size: int,
) -> None:
    """Follow agent events for a task in real-time."""
    client = STClient()
    seen_event_ids: set[str] = set()
    last_max_turn = 0

    typer.echo("\n[Following agent events... Press Ctrl+C to stop]\n")

    try:
        while True:
            try:
                result = client.get_task_agent_events(
                    task_id,
                    event_type=event_type,
                    page_size=page_size,
                )
            except APIError:
                time.sleep(2)
                continue

            events = result.get("events", [])
            max_turn = result.get("max_turn", 0)

            new_events = [e for e in events if e.get("id") not in seen_event_ids]

            for event in new_events:
                typer.echo(_format_event(event, verbose))
                typer.echo()
                event_id = event.get("id")
                if event_id:
                    seen_event_ids.add(event_id)

            if max_turn != last_max_turn and max_turn > 0:
                last_max_turn = max_turn

            try:
                task = client.get_task(task_id)
                status = task.get("status", "")
                if status in ("completed", "cancelled", "failed", "abandoned", "needs_review"):
                    typer.echo(f"\n[Task {status}]")
                    break
            except APIError:
                pass

            time.sleep(2)

    except KeyboardInterrupt:
        typer.echo("\n[Stopped]")


def _follow_session_events(
    session_id: str,
    event_type: str | None,
    verbose: bool,
    page_size: int,
) -> None:
    """Follow agent events for a session ID in real-time."""
    seen_event_ids: set[str] = set()

    typer.echo("\n[Following session events... Press Ctrl+C to stop]\n")

    try:
        while True:
            try:
                result = _get_session_events(
                    session_id,
                    event_type=event_type,
                    page_size=page_size,
                )
            except (typer.Exit, Exception):
                time.sleep(2)
                continue

            events = result.get("events", [])

            new_events = [e for e in events if e.get("id") not in seen_event_ids]

            for event in new_events:
                typer.echo(_format_event(event, verbose))
                typer.echo()
                event_id = event.get("id")
                if event_id:
                    seen_event_ids.add(event_id)

            time.sleep(2)

    except KeyboardInterrupt:
        typer.echo("\n[Stopped]")


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
            _follow_task_events(task_id, event_type, verbose, page_size)
            return

        result = _get_task_events(task_id, event_type, turn, page, page_size)

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

        _display_events(
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
        _follow_session_events(session_id, event_type, verbose, page_size)
        return

    result = _get_session_events(session_id, event_type, turn, page, page_size)

    if raw:
        output_json(result)
        return

    events = result.get("events", [])
    total = result.get("total", 0)
    max_turn = result.get("max_turn", 0)

    if not events:
        typer.echo("No events found for this session.")
        return

    _display_events(
        events, total, max_turn,
        f"Session: {session_id}",
        event_type, turn, page, verbose,
    )
