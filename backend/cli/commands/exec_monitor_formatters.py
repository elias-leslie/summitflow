"""Formatting utilities for execution log display."""

from __future__ import annotations

from typing import Any

from ..output_context import OutputContext
from .session_events_formatter import format_event as format_agent_event


def subtask_summary(subtasks: list[dict[str, Any]]) -> str:
    """Generate a compact summary of subtask statuses."""
    if not subtasks:
        return "0/0"

    total = len(subtasks)
    passed = sum(1 for s in subtasks if s.get("status") == "passed")
    failed = sum(1 for s in subtasks if s.get("status") == "failed")
    in_progress = sum(1 for s in subtasks if s.get("status") == "in_progress")

    if failed > 0:
        return f"{passed}/{total}({failed}F)"
    elif in_progress > 0:
        return f"{passed}/{total}({in_progress}W)"
    else:
        return f"{passed}/{total}"


def _format_attribute_value(key: str, value: Any) -> str | None:
    """Return a formatted attribute line, or None if the attribute should be skipped."""
    if key in ("elapsed_ms", "level", "message", "source"):
        return None
    if isinstance(value, str) and len(value) > 60:
        value = value[:60] + "..."
    return f"    {key}: {value}"


def _print_debug_attributes(attributes: dict[str, Any]) -> None:
    """Print event attributes in debug mode."""
    elapsed = attributes.get("elapsed_ms")
    if elapsed is not None:
        print(f"    elapsed: {elapsed:.1f}ms")
    for key, value in attributes.items():
        line = _format_attribute_value(key, value)
        if line is not None:
            print(line)


def _get_vis_indicator(debug: bool, visibility: str) -> str:
    """Return visibility indicator prefix for debug mode."""
    if not debug:
        return ""
    if visibility == "debug":
        return "[D] "
    if visibility == "internal":
        return "[I] "
    return ""


def _print_event_human(
    event: dict[str, Any], debug: bool, level_prefix: str, vis_indicator: str
) -> None:
    """Print a single event in human-readable format."""
    message = event.get("message", "")
    source = event.get("source", "")
    timestamp = event.get("timestamp", "")[:19]
    attributes = event.get("attributes", {})

    source_str = f" [{source}]" if source else ""
    print(f"{level_prefix} {timestamp} {vis_indicator}{message}{source_str}")

    if debug and attributes:
        _print_debug_attributes(attributes)


def print_events(
    out: OutputContext,
    events: list[Any],
    debug: bool = False,
    json_output: bool = False,
    *,
    agent_event_mode: bool = False,
) -> None:
    """Print a list of events."""
    import json

    for event in reversed(events):  # Show oldest first
        if json_output:
            # One JSON object per line for agent parsing
            print(json.dumps(event))
            continue

        if agent_event_mode:
            _print_agent_event(out, event, debug)
            continue

        timestamp = event.get("timestamp", "")[:19]  # Truncate to seconds
        level = event.get("level", "info")[:4].upper()
        message = event.get("message", "")
        visibility = event.get("visibility", "user")

        # Level colors for terminal
        level_prefix = {
            "DEBU": ".",
            "INFO": " ",
            "WARN": "!",
            "ERRO": "X",
        }.get(level, " ")

        vis_indicator = _get_vis_indicator(debug, visibility)

        if out.is_compact:
            # TOON format: timestamp|level|message
            print(f"{timestamp}|{level}|{vis_indicator}{message[:80]}")
        else:
            _print_event_human(event, debug, level_prefix, vis_indicator)


def _print_agent_event(out: OutputContext, event: dict[str, Any], debug: bool) -> None:
    """Print a task-linked Agent Hub event inside exec-log output."""
    timestamp = str(event.get("created_at", ""))[:19]
    session_id = str(event.get("session_id", ""))
    session_label = session_id[:8] if session_id else "agent"
    rendered = format_agent_event(event, verbose=debug)
    rendered = rendered.replace("\033[36m", "").replace("\033[32m", "").replace("\033[33m", "")
    rendered = rendered.replace("\033[35m", "").replace("\033[34m", "").replace("\033[90m", "")
    rendered = rendered.replace("\033[31m", "").replace("\033[0m", "")

    lines = rendered.splitlines()
    if out.is_compact:
        if not lines:
            return
        first = lines[0][:120]
        print(f"{timestamp}|AH|{session_label}|{first}")
        for line in lines[1:3]:
            print(f"{timestamp}|AH|{session_label}|{line[:120]}")
        return

    print(f"> {timestamp} Agent[{session_label}]")
    for line in lines:
        print(f"  {line}")


def print_header(
    out: OutputContext,
    task: dict[str, Any],
    subtasks: list[dict[str, Any]],
    agent_sessions: dict[str, Any],
    debug: bool = False,
    json_output: bool = False,
    *,
    hidden_attempts: int = 0,
) -> None:
    """Print task header with status and subtasks."""
    if json_output:
        return

    task_id = task.get("id", "unknown")
    title = task.get("title", "Unknown")[:50]
    status = task.get("status", "unknown")
    summary = subtask_summary(subtasks)
    sessions = agent_sessions.get("sessions", []) if isinstance(agent_sessions, dict) else []

    def _session_label(session: dict[str, Any]) -> str:
        live = session.get("live_activity") if isinstance(session, dict) else None
        role = str(session.get("agent_slug") or session.get("lane_role") or "agent")
        model = (
            session.get("effective_model")
            or session.get("requested_model")
            or session.get("id")
            or "unknown"
        )
        short_model = str(model).split("/")[-1]
        if isinstance(live, dict):
            return f"{role}:{short_model}:{live.get('health', 'unknown')}/{live.get('phase', 'unknown')}"
        return f"{role}:{short_model}:{session.get('status', 'unknown')}"

    if out.is_compact:
        session_summary = ",".join(_session_label(session) for session in sessions[:2])
        suffix = f"|AH:{session_summary}" if session_summary else ""
        if hidden_attempts:
            suffix += f"|hist={hidden_attempts}"
        print(f"EXEC:{task_id}|{status}|{summary}|{title}{suffix}")
    else:
        print(f"Task: {task_id}")
        print(f"Title: {title}")
        print(f"Status: {status}")
        if hidden_attempts:
            print(f"History: {hidden_attempts} older session(s) hidden; use st session-events --task {task_id} for full history")
        if sessions:
            print("Agent Sessions:")
            for session in sessions:
                label = _session_label(session)
                live = session.get("live_activity") if isinstance(session, dict) else None
                print(f"  {session.get('id', '?')[:8]}: {label}")
                if isinstance(live, dict) and live.get("summary"):
                    print(f"    {live['summary']}")
        if subtasks:
            print(f"Subtasks: {summary}")
            for s in subtasks:
                s_id = s.get("subtask_id", "?")
                s_status = s.get("status", "?")
                s_desc = s.get("description", "")[:40]
                print(f"  {s_id}: {s_status} - {s_desc}")
        if debug:
            print("Mode: debug (showing all visibility levels)")
        print("-" * 60)
