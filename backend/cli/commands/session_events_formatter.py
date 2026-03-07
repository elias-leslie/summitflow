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


def _session_key(event: dict[str, Any], fallback: str = "_default") -> str:
    """Resolve the session key used for memory summary tracking."""
    session_id = event.get("session_id")
    return str(session_id) if session_id else fallback


def _session_label(session_key: str) -> str:
    """Build a compact session label for aggregate headers."""
    normalized = session_key.removeprefix("session-")
    return normalized[:8]


def _summarize_memory_inject(tool_input: dict[str, Any]) -> str:
    """Summarize selected vs passive reference injection details."""
    total = int(tool_input.get("count") or 0)
    selected = int(tool_input.get("reference_selected_count") or 0)
    indexed = int(tool_input.get("reference_index_count") or 0)
    return f"loaded={total} refs:selected={selected} index={indexed}"


def _summarize_memory_cite(
    tool_input: dict[str, Any],
    selected_reference_uuids: set[str] | None = None,
) -> str:
    """Summarize citation effectiveness against selected references."""
    cited_uuids = [str(uuid) for uuid in (tool_input.get("uuids") or []) if uuid]
    total_cited = len(cited_uuids)
    selected_hits = 0
    selected_total = len(selected_reference_uuids or set())
    if selected_reference_uuids:
        selected_hits = sum(1 for uuid in cited_uuids if uuid in selected_reference_uuids)
    if selected_total > 0:
        return (
            f"cited={total_cited} selected_cited={selected_hits}/{selected_total}"
        )
    return f"cited={total_cited}"


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


def _format_memory_event_content(
    event: dict[str, Any],
    verbose: bool,
    selected_reference_uuids: set[str] | None = None,
) -> str:
    """Extract display content for memory events."""
    tool_input = event.get("tool_input")
    if not tool_input:
        return event.get("content") or ""
    if verbose:
        return json.dumps(tool_input, indent=2)
    event_type = event.get("event_type")
    if event_type == "memory_inject":
        return _summarize_memory_inject(tool_input)
    if event_type == "memory_cite":
        return _summarize_memory_cite(tool_input, selected_reference_uuids)
    return event.get("content") or ""


def _selected_refs_from_memory_inject(event: dict[str, Any]) -> set[str]:
    """Extract selected reference UUIDs from a memory injection event."""
    tool_input = event.get("tool_input") or {}
    uuids = tool_input.get("reference_selected_uuids") or []
    return {str(uuid) for uuid in uuids if uuid}


def build_memory_effectiveness_summary(
    events: list[dict[str, Any]],
) -> dict[str, dict[str, int | str]]:
    """Aggregate selected/index/cited reference metrics per session key."""
    summary: dict[str, dict[str, int | str]] = {}
    selected_refs_by_session: dict[str, set[str]] = {}

    for event in events:
        session_key = _session_key(event)
        session_summary = summary.setdefault(
            session_key,
            {
                "selected": 0,
                "indexed": 0,
                "selected_cited": 0,
                "total_cited": 0,
                "session_label": _session_label(session_key),
            },
        )
        tool_input = event.get("tool_input") or {}
        event_type = event.get("event_type")

        if event_type == "memory_inject":
            selected_count = int(tool_input.get("reference_selected_count") or 0)
            indexed_count = int(tool_input.get("reference_index_count") or 0)
            session_summary["selected"] = int(session_summary["selected"]) + selected_count
            session_summary["indexed"] = int(session_summary["indexed"]) + indexed_count
            selected_refs_by_session[session_key] = _selected_refs_from_memory_inject(event)
            continue

        if event_type == "memory_cite":
            cited_uuids = [str(uuid) for uuid in (tool_input.get("uuids") or []) if uuid]
            selected_uuids = selected_refs_by_session.get(session_key, set())
            session_summary["total_cited"] = int(session_summary["total_cited"]) + len(cited_uuids)
            session_summary["selected_cited"] = int(session_summary["selected_cited"]) + sum(
                1 for uuid in cited_uuids if uuid in selected_uuids
            )

    return {
        key: value
        for key, value in summary.items()
        if int(value["selected"]) > 0
        or int(value["indexed"]) > 0
        or int(value["selected_cited"]) > 0
        or int(value["total_cited"]) > 0
    }


def _render_memory_effectiveness_summary(
    events: list[dict[str, Any]],
    session_ids: list[str] | None,
) -> list[str]:
    """Render compact memory summary lines for the header block."""
    summary = build_memory_effectiveness_summary(events)
    if not summary:
        return []

    lines = [" Memory:"]
    ordered_keys: list[str]
    if session_ids:
        ordered_keys = [session_id for session_id in session_ids if session_id in summary]
    else:
        ordered_keys = list(summary.keys())

    if len(ordered_keys) == 1:
        item = summary[ordered_keys[0]]
        selected = int(item["selected"])
        indexed = int(item["indexed"])
        selected_cited = int(item["selected_cited"])
        rate = f"{round((selected_cited / selected) * 100):d}%" if selected > 0 else "0%"
        lines.append(
            f" refs selected={selected} | index={indexed} | selected cited={selected_cited}/{selected} ({rate})"
        )
        return lines

    total_selected = sum(int(summary[key]["selected"]) for key in ordered_keys)
    total_indexed = sum(int(summary[key]["indexed"]) for key in ordered_keys)
    total_selected_cited = sum(int(summary[key]["selected_cited"]) for key in ordered_keys)
    total_rate = (
        f"{round((total_selected_cited / total_selected) * 100):d}%"
        if total_selected > 0
        else "0%"
    )
    lines.append(
        f" total selected={total_selected} | index={total_indexed} | selected cited={total_selected_cited}/{total_selected} ({total_rate})"
    )
    for key in ordered_keys:
        item = summary[key]
        selected = int(item["selected"])
        indexed = int(item["indexed"])
        selected_cited = int(item["selected_cited"])
        rate = f"{round((selected_cited / selected) * 100):d}%" if selected > 0 else "0%"
        lines.append(
            f" {item['session_label']!s}: refs={selected} | index={indexed} | selected cited={selected_cited}/{selected} ({rate})"
        )
    return lines


def _display_events_header(
    total: int,
    max_turn: int,
    label: str,
    event_type: str | None,
    turn_filter: int | None,
    session_ids: list[str] | None,
    events: list[dict[str, Any]],
) -> None:
    """Print the header block for the events display."""
    typer.echo(f"\n {label}")
    if session_ids:
        typer.echo(f" Sessions: {len(session_ids)} ({', '.join(s[:8] for s in session_ids)})")
    typer.echo(f" Events: {total} | Max turn: {max_turn}")
    for line in _render_memory_effectiveness_summary(events, session_ids):
        typer.echo(line)
    if event_type:
        typer.echo(f" Filter: type={event_type}")
    if turn_filter is not None:
        typer.echo(f" Filter: turn={turn_filter}")
    typer.echo("-" * 60)


def _display_events_body(events: list[dict[str, Any]], verbose: bool) -> None:
    """Print each event, emitting session separator lines as needed."""
    current_session: str | None = None
    session_index = 0
    selected_refs_by_session: dict[str, set[str]] = {}
    for event in events:
        event_session = event.get("session_id")
        if event_session and event_session != current_session:
            session_index += 1
            current_session = event_session
            typer.echo(f"\033[33m--- Session {session_index}: {event_session[:8]} ---\033[0m")
        session_key = event_session or current_session or "_default"
        if event.get("event_type") == "memory_inject":
            selected_refs_by_session[session_key] = _selected_refs_from_memory_inject(event)

        if event.get("event_type") in {"memory_inject", "memory_cite"}:
            event_for_display = dict(event)
            event_for_display["content"] = _format_memory_event_content(
                event,
                verbose,
                selected_refs_by_session.get(session_key),
            )
            typer.echo(format_event(event_for_display, verbose))
        else:
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
    _display_events_header(total, max_turn, label, event_type, turn_filter, session_ids, events)
    _display_events_body(events, verbose)
    if len(events) < total:
        typer.echo(f"Showing {len(events)} of {total} events (page {page})")
