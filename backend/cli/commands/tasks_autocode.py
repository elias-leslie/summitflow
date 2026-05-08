"""Task autocode functionality."""

from __future__ import annotations

from typing import Any

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error, output_json

_READY_SELECTION_WINDOW = 25


def autocode_task(
    task_id: str | None,
    dry_run: bool,
    at: str | None,
    client: STClient,
    *,
    next_task: bool = False,
) -> None:
    """Queue task for autonomous execution via Hatchet."""
    task_id, selected_from_ready = _resolve_task_id(task_id, client, next_task=next_task)
    task = _fetch_task(task_id, client)
    client = _get_task_client(task, client)
    subtasks = _fetch_subtasks(task_id, client)
    _validate_task_for_autocode(task_id, task, subtasks, client)
    schedule = _parse_schedule(at)

    if dry_run:
        _output_dry_run(task_id, subtasks, schedule, selected_from_ready=selected_from_ready)
        return

    _queue_task_for_execution(task_id, client)
    _output_queue_result(task_id, schedule, selected_from_ready=selected_from_ready)


def _resolve_task_id(
    task_id: str | None,
    client: STClient,
    *,
    next_task: bool,
) -> tuple[str, bool]:
    """Resolve explicit task id or select the top ready-queue task."""
    if not next_task:
        if task_id:
            return task_id, False
        output_error("Task id required unless --next is provided.")
        raise typer.Exit(1)

    if task_id:
        output_error("Pass either a task id or --next, not both.")
        raise typer.Exit(1)

    try:
        result = client.list_ready(limit=_READY_SELECTION_WINDOW)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    tasks = result.get("tasks") or []
    if not tasks:
        project_id = getattr(client, "project_id", None) or "current project"
        output_error(f"No execution-ready tasks found for {project_id}.")
        raise typer.Exit(1)

    from app.services.ready_task_ranking import sort_ready_tasks

    selected = sort_ready_tasks([dict(task) for task in tasks])[0]
    selected_id = selected.get("id")
    if not isinstance(selected_id, str) or not selected_id:
        output_error("Ready queue returned a task without an id.")
        raise typer.Exit(1)
    return selected_id, True


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
    if current_status == "running":
        output_error(f"Task {task_id} is already running.")
        raise typer.Exit(1)
    if current_status in ("completed", "failed", "cancelled"):
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


def _parse_schedule(at: str | None) -> Any | None:
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
    schedule: Any | None,
    *,
    selected_from_ready: bool,
) -> None:
    """Output dry-run results."""
    incomplete = [s for s in subtasks if not s.get("passes")]
    result: dict[str, object] = {
        "task_id": task_id,
        "status": "dry_run",
        "selected_from_ready": selected_from_ready,
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
        client.execute_task(task_id)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None


def _output_queue_result(task_id: str, schedule: Any | None, *, selected_from_ready: bool) -> None:
    """Output task queueing result."""
    if schedule and hasattr(schedule, "timestamp"):
        msg = f"Task scheduled for {schedule.timestamp.strftime('%Y-%m-%d %H:%M UTC')}"
        output_json({
            "task_id": task_id,
            "status": "scheduled",
            "selected_from_ready": selected_from_ready,
            "scheduled_for": schedule.timestamp.isoformat(),
            "message": msg,
        })
    else:
        msg = f"Task queued for immediate execution. Monitor via: st context {task_id}"
        output_json({
            "task_id": task_id,
            "status": "queued",
            "dispatch": "immediate",
            "selected_from_ready": selected_from_ready,
            "message": msg,
        })
