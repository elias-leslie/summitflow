"""Follow-mode polling logic for execution log monitoring."""

from __future__ import annotations

import json
import time

from ..client import APIError, STClient
from ..output_context import OutputContext
from .exec_monitor_formatters import print_events


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
        current_status = status
        current_last_event_id = last_event_id

        while True:
            time.sleep(2)

            # Check task status
            try:
                task = client.get_task(task_id)
                new_status = task.get("status", "unknown")

                if new_status != current_status:
                    current_status = new_status
                    if json_output:
                        print(json.dumps({"type": "status_change", "status": current_status}))
                    else:
                        print(f"\n[Status changed: {current_status}]")

                if current_status in ("completed", "cancelled", "failed", "closed"):
                    if json_output:
                        print(json.dumps({"type": "task_ended", "status": current_status}))
                    else:
                        print(f"\n[Task {current_status}]")
                    break

                # Get new events
                new_events = client.get_events(project_id, task_id, limit=10, include_debug=debug)
                events_list = (
                    new_events.get("events", []) if isinstance(new_events, dict) else new_events
                )

                if events_list:
                    # Filter to only new events
                    if current_last_event_id:
                        new_only = [e for e in events_list if e.get("id") != current_last_event_id]
                        # Check if we have events newer than last
                        if new_only and events_list[0].get("id") != current_last_event_id:
                            print_events(out, new_only, debug, json_output)
                            current_last_event_id = events_list[0].get("id")
                    else:
                        current_last_event_id = events_list[0].get("id")
            except APIError:
                # Ignore transient errors in follow mode
                pass

    except KeyboardInterrupt:
        if not json_output:
            print("\n[Stopped]")
