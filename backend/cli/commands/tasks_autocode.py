"""Task autocode functionality."""

from __future__ import annotations

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error, output_json


def autocode_task(
    task_id: str,
    dry_run: bool,
    at: str | None,
    client: STClient,
) -> None:
    """Queue task for autonomous execution via Hatchet."""
    task = _fetch_task(task_id, client)
    client = _get_task_client(task, client)
    subtasks = _fetch_subtasks(task_id, client)
    _validate_task_for_autocode(task_id, task, subtasks, client)
    schedule = _parse_schedule(at)

    if dry_run:
        _output_dry_run(task_id, subtasks, schedule)
        return

    _queue_task_for_execution(task_id, client)
    _output_queue_result(task_id, schedule)


def _fetch_task(task_id: str, client: STClient) -> dict[str, object]:
    """Fetch task details."""
    try:
        return client.get_task(task_id)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None


def _get_task_client(task: dict[str, object], client: STClient) -> STClient:
    """Get appropriate client for the task's project."""
    task_project_id = task.get("project_id", "summitflow")
    if task_project_id != client.project_id:
        return STClient(project_id=str(task_project_id), require_project=False)
    return client


def _fetch_subtasks(task_id: str, client: STClient) -> list[dict[str, object]]:
    """Fetch task subtasks."""
    try:
        subtasks_response = client.get_subtasks(task_id)
        return list(subtasks_response.get("subtasks", []))
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None


def _validate_task_for_autocode(
    task_id: str,
    task: dict[str, object],
    subtasks: list[dict[str, object]],
    client: STClient,
) -> None:
    """Validate that task can be autocoded."""
    current_status = task.get("status", "pending")
    if current_status in ("running", "queue"):
        output_error(f"Task {task_id} is already {current_status}.")
        raise typer.Exit(1)
    if current_status in ("completed", "merged"):
        output_error(f"Task {task_id} is already {current_status}.")
        raise typer.Exit(1)
    readiness = client.validate_ready(task_id)
    if not readiness.get("ready", False):
        output_error(f"Task {task_id} is not execution-ready for autocode.")
        for issue in readiness.get("issues", [])[:8]:
            output_error(f"  - {issue}")
        for suggestion in readiness.get("suggestions", [])[:5]:
            output_error(f"  hint: {suggestion}")
        raise typer.Exit(1)


def _parse_schedule(at: str | None) -> object | None:
    """Parse schedule from --at parameter."""
    if not at:
        return None

    from app.scheduling.types import OnceSchedule, parse_at_time

    try:
        scheduled_time = parse_at_time(at)
        return OnceSchedule(timestamp=scheduled_time)
    except ValueError as e:
        output_error(f"Invalid --at value: {e}")
        raise typer.Exit(1) from None


def _output_dry_run(
    task_id: str,
    subtasks: list[dict[str, object]],
    schedule: object | None,
) -> None:
    """Output dry-run results."""
    incomplete = [s for s in subtasks if not s.get("passes")]
    result: dict[str, object] = {
        "task_id": task_id,
        "status": "dry_run",
        "subtasks_total": len(subtasks),
        "subtasks_incomplete": len(incomplete),
        "next_subtask": incomplete[0]["subtask_id"] if incomplete else None,
        "message": f"Would queue {task_id} for autonomous execution",
    }
    if schedule and hasattr(schedule, "timestamp"):
        result["scheduled_for"] = schedule.timestamp.isoformat()
    output_json(result)


def _queue_task_for_execution(task_id: str, client: STClient) -> None:
    """Update task status to queue for execution."""
    try:
        client.update_status(task_id, status="queue")
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None


def _output_queue_result(task_id: str, schedule: object | None) -> None:
    """Output task queueing result."""
    if schedule and hasattr(schedule, "timestamp"):
        msg = f"Task scheduled for {schedule.timestamp.strftime('%Y-%m-%d %H:%M UTC')}"
        output_json({
            "task_id": task_id,
            "status": "scheduled",
            "scheduled_for": schedule.timestamp.isoformat(),
            "message": msg,
        })
    else:
        msg = f"Task queued for immediate execution. Monitor via: st context {task_id}"
        output_json({
            "task_id": task_id,
            "status": "queued",
            "dispatch": "immediate",
            "message": msg,
        })
