"""Session state management for execution handoff and wind-down."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ....storage import log_task_event
from ....storage import tasks as task_store
from ....storage.subtasks import insert_subtask_summary
from .events import emit_log


@dataclass(frozen=True)
class WindDownState:
    """Outcome describing an execution pass that paused instead of terminating."""

    paused: bool
    reason: str | None = None


def extract_handoff_summary(subtask_id: str, agent_response: str) -> None:
    """Extract and save handoff summary from agent response."""
    summary = agent_response[:1000] if len(agent_response) > 1000 else agent_response
    insert_subtask_summary(subtask_id, summary=summary, files_modified=[], decisions_made=[])


def wind_down(
    task_id: str,
    results: list[dict[str, Any]],
    incomplete: list[dict[str, Any]],
    reason: str,
) -> WindDownState:
    """Preserve session state when execution pauses."""
    completed_ids = [r["subtask_id"] for r in results if r.get("status") == "passed"]
    failed_ids = [r["subtask_id"] for r in results if r.get("status") == "failed"]
    remaining_ids = [
        s.get("subtask_id", "")
        for s in incomplete
        if s.get("subtask_id") not in completed_ids + failed_ids
    ]

    last_failed = failed_ids[-1] if failed_ids else None

    wind_down_log = f"""SESSION END {datetime.now(UTC).strftime("%Y-%m-%d %H:%M")}:
COMPLETED: {", ".join(completed_ids) if completed_ids else "none"}
IN PROGRESS: {last_failed or "none"}
REMAINING: {", ".join(remaining_ids) if remaining_ids else "none"}

NEXT SESSION:
1. Resume at: {last_failed or remaining_ids[0] if remaining_ids else "complete"}
2. Reason for pause: {reason}
"""

    log_task_event(task_id, wind_down_log)
    current_task = task_store.get_task(task_id) or {}
    current_status = str(current_task.get("status") or "")
    # Preserve terminal status: if the orchestrator/agent already declared a
    # final state (completed/failed/cancelled), wind-down must not erase it.
    # Only reset mid-flight runs back to pending so the queue can re-pick them.
    if current_status in {"completed", "failed", "cancelled"}:
        emit_log(task_id, "info", f"Session paused (status preserved: {current_status}): {reason}")
    else:
        task_store.update_task_status(task_id, "pending")
        emit_log(task_id, "info", f"Session paused: {reason}")
    return WindDownState(paused=True, reason=reason)
