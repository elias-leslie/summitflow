"""Real-time following/polling functions for session events."""

from __future__ import annotations

import time

import typer

from ..client import APIError, STClient
from .session_events_client import get_session_events
from .session_events_formatter import format_event


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
                typer.echo(format_event(event, verbose))
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
            try:
                result = get_session_events(
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
                typer.echo(format_event(event, verbose))
                typer.echo()
                event_id = event.get("id")
                if event_id:
                    seen_event_ids.add(event_id)

            time.sleep(2)

    except KeyboardInterrupt:
        typer.echo("\n[Stopped]")
