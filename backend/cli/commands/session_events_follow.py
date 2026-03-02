"""Real-time following/polling functions for session events."""

from __future__ import annotations

import time

import typer

from ..client import APIError, STClient
from .session_events_client import get_session_events
from .session_events_formatter import format_event


def _emit_new_events(
    events: list[dict],
    seen_event_ids: set[str],
    verbose: bool,
) -> None:
    """Print events not yet seen and track their IDs."""
    new_events = [e for e in events if e.get("id") not in seen_event_ids]
    for event in new_events:
        typer.echo(format_event(event, verbose))
        typer.echo()
        event_id = event.get("id")
        if event_id:
            seen_event_ids.add(event_id)


def _is_task_terminal(client: STClient, task_id: str) -> str:
    """Return terminal status string if task is done, else empty string."""
    terminal_statuses = {"completed", "cancelled", "failed", "abandoned", "needs_review"}
    try:
        task = client.get_task(task_id)
        status = task.get("status", "")
        if status in terminal_statuses:
            return status
    except APIError:
        pass
    return ""


def _poll_task_events(
    client: STClient,
    task_id: str,
    event_type: str | None,
    page_size: int,
    verbose: bool,
    seen_event_ids: set[str],
    last_max_turn: int,
) -> tuple[bool, int]:
    """Poll once for task events. Returns (should_break, updated_last_max_turn)."""
    try:
        result = client.get_task_agent_events(
            task_id,
            event_type=event_type,
            page_size=page_size,
        )
    except APIError:
        time.sleep(2)
        return False, last_max_turn

    events = result.get("events", [])
    max_turn = result.get("max_turn", 0)

    _emit_new_events(events, seen_event_ids, verbose)

    if max_turn != last_max_turn and max_turn > 0:
        last_max_turn = max_turn

    terminal_status = _is_task_terminal(client, task_id)
    if terminal_status:
        typer.echo(f"\n[Task {terminal_status}]")
        return True, last_max_turn

    return False, last_max_turn


def follow_task_events(
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
            should_break, last_max_turn = _poll_task_events(
                client, task_id, event_type, page_size, verbose, seen_event_ids, last_max_turn
            )
            if should_break:
                break
            time.sleep(2)
    except KeyboardInterrupt:
        typer.echo("\n[Stopped]")


def _poll_session_events(
    session_id: str,
    event_type: str | None,
    page_size: int,
    verbose: bool,
    seen_event_ids: set[str],
) -> None:
    """Poll once for session events, printing any new ones."""
    try:
        result = get_session_events(
            session_id,
            event_type=event_type,
            page_size=page_size,
        )
    except (typer.Exit, Exception):
        time.sleep(2)
        return

    events = result.get("events", [])
    _emit_new_events(events, seen_event_ids, verbose)


def follow_session_events(
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
            _poll_session_events(session_id, event_type, page_size, verbose, seen_event_ids)
            time.sleep(2)
    except KeyboardInterrupt:
        typer.echo("\n[Stopped]")
