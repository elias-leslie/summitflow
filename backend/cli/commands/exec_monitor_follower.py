"""Follow-mode polling logic for execution log monitoring."""

from __future__ import annotations

import json
import time

from ..client import APIError, STClient
from ..output_context import OutputContext
from .exec_monitor_formatters import print_events

_FINAL_TASK_STATUSES = ("completed", "cancelled", "failed", "closed")


def _poll_once(
    out: OutputContext,
    task_id: str,
    project_id: str,
    client: STClient,
    debug: bool,
    json_output: bool,
    current_status: str,
    last_event_id: str | None,
) -> tuple[str, str | None, bool]:
    """Poll once; return (new_status, new_last_event_id, should_stop)."""
    try:
        task = client.get_task(task_id)
        new_status = task.get("status", "unknown")
        if new_status != current_status:
            current_status = new_status
            msg = {"type": "status_change", "status": current_status}
            print(json.dumps(msg) if json_output else f"\n[Status changed: {current_status}]")
        if current_status in _FINAL_TASK_STATUSES:
            msg = {"type": "task_ended", "status": current_status}
            print(json.dumps(msg) if json_output else f"\n[Task {current_status}]")
            return current_status, last_event_id, True
        raw = client.get_events(project_id, task_id, limit=10, include_debug=debug)
        events = raw.get("events", []) if isinstance(raw, dict) else raw
        if events and last_event_id:
            new_only = [e for e in events if e.get("id") != last_event_id]
            if new_only and events[0].get("id") != last_event_id:
                print_events(out, new_only, debug, json_output)
                last_event_id = events[0].get("id")
        elif events:
            last_event_id = events[0].get("id")
    except APIError:
        pass
    return current_status, last_event_id, False


def follow_events(
    out: OutputContext,
    task_id: str,
    project_id: str,
    status: str,
    last_event_id: str | None,
    client: STClient,
    debug: bool = False,
    json_output: bool = False,
) -> None:
    """Poll for new events in follow mode."""
    if not json_output:
        print("\n[Following... Press Ctrl+C to stop]\n")
    try:
        while True:
            time.sleep(2)
            status, last_event_id, stop = _poll_once(
                out, task_id, project_id, client, debug, json_output, status, last_event_id,
            )
            if stop:
                break
    except KeyboardInterrupt:
        if not json_output:
            print("\n[Stopped]")
