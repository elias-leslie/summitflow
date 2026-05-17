"""Task lifecycle management commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from ..client import APIError, STClient
from ..context import require_task_id
from ..output import handle_api_error, output_error, output_success, output_task


def _cleanup_safe_pause_residue(task_id: str, project_id: str | None) -> str | None:
    """Remove already-merged checkpoint residue after pausing a task."""
    if not project_id:
        return None
    from ..lib.checkpoint import get_active_checkpoints
    from .cleanup_analysis import CleanupAction, analyze_checkpoint, cleanup_checkpoint

    for checkpoint in get_active_checkpoints(project_id):
        if checkpoint.task_id != task_id:
            continue
        analysis = analyze_checkpoint(checkpoint)
        if analysis.action not in {CleanupAction.SAFE_DELETE, CleanupAction.ALREADY_MERGED}:
            return f"checkpoint_kept:{analysis.action.value}"
        cleaned, message = cleanup_checkpoint(analysis, force=False)
        return "checkpoint_cleaned" if cleaned else f"checkpoint_kept:{message}"
    return None


def cancel_task_command(
    task_id: str | None,
    reason: str,
) -> None:
    """Cancel a task (mark as cancelled from any state)."""
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        task = client.cancel_task(task_id, reason=reason or None)
    except APIError as e:
        handle_api_error(e)
        return

    task["cancel_reason"] = reason
    output_task(task)


def pause_task_command(
    task_id: str | None,
    reason: str,
) -> None:
    """Pause a task and release any active claim while preserving task state."""
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        task = client.pause_task(task_id, reason=reason or None)
    except APIError as e:
        handle_api_error(e)
        return

    cleanup_result = _cleanup_safe_pause_residue(task_id, task.get("project_id"))
    if reason:
        task["pause_reason"] = reason
    output_task(task)
    if cleanup_result:
        output_success(cleanup_result)


def delete_task_command(
    task_id: str | None,
) -> None:
    """Delete a task."""
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.delete_task(task_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"Deleted task {task_id}")


def reopen_task_command(
    task_id: str | None,
    reason: str,
) -> None:
    """Reopen a task by moving it back to pending.

    Accepts any non-pending state (paused, completed, cancelled, failed).
    """
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        task = client.reopen_task(task_id, reason=reason or None)
    except APIError as e:
        handle_api_error(e)
        return

    if reason:
        task["reopen_reason"] = reason
    output_task(task)


def update_task_command(
    task_id: str,
    *,
    title: str | None = None,
    priority: int | None = None,
    labels: str | None = None,
    description: str | None = None,
    plan: Path | None = None,
) -> None:
    """Update in-flight task fields. Refuses status changes (use lifecycle verbs)."""
    task_id = require_task_id(task_id)
    fields: dict[str, Any] = {}
    if title is not None:
        fields["title"] = title
    if priority is not None:
        fields["priority"] = priority
    if labels is not None:
        fields["labels"] = [item.strip() for item in labels.split(",") if item.strip()]
    if description is not None:
        fields["description"] = description

    if not fields and plan is None:
        output_error(
            "st update needs at least one field to change.\n"
            "Resolution: pass --title, --priority, --labels, --description, or --plan"
        )
        raise typer.Exit(1)

    client = STClient()
    try:
        task = client.update_task(task_id, **fields) if fields else client.get_task(task_id)
    except APIError as e:
        handle_api_error(e)
        return

    if plan is not None:
        _apply_plan_swap(task_id, plan)
        try:
            task = client.get_task(task_id)
        except APIError as e:
            handle_api_error(e)
            return
        task["plan_swapped"] = True

    output_task(task)


def _apply_plan_swap(task_id: str, plan: Path) -> None:
    """Replace the task's spirit plan and reset plan_status to draft."""
    try:
        raw = json.loads(plan.read_text())
    except (OSError, json.JSONDecodeError) as e:
        output_error(
            f"Failed to read plan {plan}: {e}\n"
            "Resolution: pass a JSON plan file with at least {title, subtasks}"
        )
        raise typer.Exit(1) from None

    from app.storage import task_spirit as spirit_store

    from .tasks_helpers import upsert_task_spirit_from_plan
    upsert_task_spirit_from_plan(task_id, raw)
    spirit_store.set_plan_status(task_id, "draft", actor="st-update-plan")
