"""Task lifecycle management commands."""

from __future__ import annotations

from ..client import APIError, STClient
from ..context import require_task_id
from ..output import handle_api_error, output_success, output_task


def cancel_task_command(
    task_id: str | None,
    reason: str,
) -> None:
    """Cancel a task (mark as cancelled from any state).

    Use this for tasks that are invalid, obsolete, or no longer needed.
    Works from any non-terminal state (pending, running, paused, failed).

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st cancel task-abc123 -r "Invalid: file doesn't exist"
        st cancel -r "Obsolete: already fixed"    # Uses active context
    """
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

    if reason:
        task["pause_reason"] = reason
    output_task(task)


def resume_task_command(
    task_id: str | None,
    reason: str,
) -> None:
    """Resume a paused task by moving it back to pending."""
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        task = client.resume_task(task_id, reason=reason or None)
    except APIError as e:
        handle_api_error(e)
        return

    if reason:
        task["resume_reason"] = reason
    output_task(task)


def delete_task_command(
    task_id: str | None,
) -> None:
    """Delete a task.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st delete task-abc123
    """
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

    Use this when a task was closed incorrectly or needs another execution pass.

    Examples:
        st reopen task-abc123 -r "False completion during reconcile"
        st reopen task-abc123
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
