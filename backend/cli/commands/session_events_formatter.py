"""Formatting and display functions for session events."""

from __future__ import annotations

import json
from typing import Any

import typer

_TYPE_COLORS = {
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
_RESET = "\033[0m"


def summarize_tool_input(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Extract human-readable summary from tool input."""
    if tool_name == "bash":
        cmd = tool_input.get("command", "")
        return f"$ {cmd[:150]}" if cmd else ""
    if tool_name == "read_file":
        path = tool_input.get("path", "")
        offset = tool_input.get("offset")
        return f"path={path}" + (f" offset={offset}" if offset else "")
    if tool_name == "write_file":
        path = tool_input.get("path", "")
        content = tool_input.get("content", "")
        return f"path={path} ({len(content)} bytes)"
    if tool_name in ("grep", "search"):
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", ".")
        return f"pattern={pattern!r} path={path}"
    if tool_name == "glob":
        pattern = tool_input.get("pattern", "")
        return f"pattern={pattern!r}"
    return json.dumps(tool_input)[:120]


def summarize_tool_output(tool_output: dict[str, Any]) -> str:
    """Extract human-readable summary from tool output."""
    content: str = tool_output.get("content", "")
    is_error = tool_output.get("is_error", False)
    if is_error:
        return f"ERROR: {content[:150]}"
    if len(content) <= 120:
        return content
    lines = content.split("\n")
    return f"({len(lines)} lines) {lines[0][:100]}..."


def _format_event_header(event: dict[str, Any], verbose: bool) -> str:
    """Build the colored header line for an event."""
    event_type = event.get("event_type", "unknown")
    turn = event.get("turn", 0)
    seq = event.get("sequence", 0)
    tool_name = event.get("tool_name")
    tokens = event.get("tokens")
    model = event.get("model_used")

    color = _TYPE_COLORS.get(event_type, "")
    header = f"{color}[{turn}.{seq}] {event_type}{_RESET}"
    if tool_name:
        header += f" ({tool_name})"
    if tokens:
        header += f" [{tokens} tokens]"
    if model and verbose:
        header += f" [{model}]"
    return header


def _format_tool_use_content(event: dict[str, Any], verbose: bool) -> str:
    """Extract display content for a tool_use event."""
    tool_name = event.get("tool_name")
    tool_input = event.get("tool_input")
    if not tool_input:
        return ""
    if verbose:
        return json.dumps(tool_input, indent=2)
    if tool_name:
        return summarize_tool_input(tool_name, tool_input)
    return json.dumps(tool_input)[:120]


def _format_tool_result_content(event: dict[str, Any], verbose: bool) -> str:
    """Extract display content for a tool_result event."""
    tool_output = event.get("tool_output")
    if not tool_output:
        return ""
    if verbose:
        return json.dumps(tool_output, indent=2)
    return summarize_tool_output(tool_output)


def format_event(event: dict[str, Any], verbose: bool = False) -> str:
    """Format a single event for display."""
    event_type = event.get("event_type", "unknown")
    content = event.get("content") or ""

    if event_type == "tool_use":
        content = _format_tool_use_content(event, verbose)
    elif event_type == "tool_result":
        content = _format_tool_result_content(event, verbose)

    if content and len(content) > 200 and not verbose:
        content = content[:200] + "..."

    header = _format_event_header(event, verbose)
    if content:
        indented = "  " + content.replace("\n", "\n  ")
        return f"{header}\n{indented}"
    return header


def _display_events_header(
    total: int,
    max_turn: int,
    label: str,
    event_type: str | None,
    turn_filter: int | None,
    session_ids: list[str] | None,
) -> None:
    """Print the header block for the events display."""
    typer.echo(f"\n {label}")
    if session_ids:
        typer.echo(f" Sessions: {len(session_ids)} ({', '.join(s[:8] for s in session_ids)})")
    typer.echo(f" Events: {total} | Max turn: {max_turn}")
    if event_type:
        typer.echo(f" Filter: type={event_type}")
    if turn_filter is not None:
        typer.echo(f" Filter: turn={turn_filter}")
    typer.echo("-" * 60)


def _display_events_body(events: list[dict[str, Any]], verbose: bool) -> None:
    """Print each event, emitting session separator lines as needed."""
    current_session: str | None = None
    session_index = 0
    for event in events:
        event_session = event.get("session_id")
        if event_session and event_session != current_session:
            session_index += 1
            current_session = event_session
            typer.echo(f"\033[33m--- Session {session_index}: {event_session[:8]} ---\033[0m")
        typer.echo(format_event(event, verbose))
        typer.echo()


def display_events(
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
    _display_events_header(total, max_turn, label, event_type, turn_filter, session_ids)
    _display_events_body(events, verbose)
    if len(events) < total:
        typer.echo(f"Showing {len(events)} of {total} events (page {page})")
