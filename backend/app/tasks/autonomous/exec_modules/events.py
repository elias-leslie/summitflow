"""Event emission utilities for execution timeline and progress tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ....services.pubsub import publish_ws_event
from ....storage.events import EventLevel, EventVisibility


def emit_log(
    task_id: str,
    level: str,
    message: str,
    source: str = "execution",
    *,
    project_id: str | None = None,
    visibility: EventVisibility = "user",
    sequence: int | None = None,
) -> None:
    """Emit a log event via Redis pub/sub."""
    level_map: dict[str, EventLevel] = {
        "info": "info",
        "warn": "warning",
        "warning": "warning",
        "error": "error",
        "debug": "debug",
    }

    data: dict[str, Any] = {"level": level, "message": message, "source": source}
    if sequence is not None:
        data["sequence"] = sequence

    publish_ws_event(
        task_id,
        {
            "type": "log",
            "task_id": task_id,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        },
        project_id=project_id,
        trace_id=task_id,
        source=source,
        level=level_map.get(level, "info"),
        visibility=visibility,
    )


def emit_progress(
    task_id: str,
    subtask_id: str | None = None,
    step: int | None = None,
    status: str = "in_progress",
    total_subtasks: int | None = None,
    completed_subtasks: int | None = None,
    *,
    project_id: str | None = None,
) -> None:
    """Emit a progress event via Redis pub/sub."""
    if subtask_id:
        if step is not None:
            message = f"Subtask {subtask_id} step {step}: {status}"
        else:
            message = f"Subtask {subtask_id}: {status}"
    elif total_subtasks is not None:
        message = f"Progress: {completed_subtasks or 0}/{total_subtasks} subtasks"
    else:
        message = f"Status: {status}"

    publish_ws_event(
        task_id,
        {
            "type": "progress",
            "task_id": task_id,
            "data": {
                "message": message,
                "subtask_id": subtask_id,
                "step": step,
                "status": status,
                "total_subtasks": total_subtasks,
                "completed_subtasks": completed_subtasks,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        },
        project_id=project_id,
        trace_id=task_id,
        source="orchestrator",
        visibility="user",
    )


def emit_error(
    task_id: str,
    error: str,
    recoverable: bool = True,
    *,
    project_id: str | None = None,
) -> None:
    """Emit an error event via Redis pub/sub."""
    publish_ws_event(
        task_id,
        {
            "type": "error",
            "task_id": task_id,
            "data": {"message": error, "error": error, "recoverable": recoverable},
            "timestamp": datetime.now(UTC).isoformat(),
        },
        project_id=project_id,
        trace_id=task_id,
        source="orchestrator",
        level="error",
        visibility="user",
    )


def emit_progress_log(
    task_id: str,
    subtask_id: str,
    progress_log: list[Any],
    *,
    project_id: str | None = None,
) -> None:
    """Emit progress_log entries from Agent Hub response as timeline events.

    Args:
        task_id: Task ID for event correlation
        subtask_id: Subtask being executed
        progress_log: List of AgentProgress entries from agentic completion response
        project_id: Project ID for event scoping
    """
    if not progress_log:
        return

    seq = 0
    for entry in progress_log:
        turn = getattr(entry, "turn", 0)
        status = getattr(entry, "status", "unknown")
        message = getattr(entry, "message", "")
        tool_calls = getattr(entry, "tool_calls", [])
        tool_results = getattr(entry, "tool_results", [])
        thinking = getattr(entry, "thinking", None)

        # Map status to log level
        level = "info"
        if status == "error":
            level = "error"
        elif status in ("thinking", "tool_use"):
            level = "debug"

        # Determine visibility based on content
        visibility: EventVisibility = "user"
        if thinking or status == "thinking":
            visibility = "internal"

        # Build event message
        if tool_calls:
            tool_names = [tc.get("name", "?") for tc in tool_calls]
            event_message = f"Turn {turn}: {status} - tools: {', '.join(tool_names)}"
        else:
            event_message = f"Turn {turn}: {status}"
            if message and message != f"Turn {turn}: sending to Gemini":
                event_message = f"Turn {turn}: {message}"

        emit_log(
            task_id,
            level,
            event_message,
            source="agent",
            project_id=project_id,
            visibility=visibility,
            sequence=seq,
        )
        seq += 1

        # Emit tool results as separate events for detail
        for result in tool_results:
            tool_id = result.get("id", "?")
            content_preview = str(result.get("content", ""))[:200]
            emit_log(
                task_id,
                "debug",
                f"  Tool result [{tool_id}]: {content_preview}",
                source="agent",
                project_id=project_id,
                visibility="internal",
                sequence=seq,
            )
            seq += 1
