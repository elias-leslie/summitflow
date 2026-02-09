"""Task lifecycle management commands (cancel, delete)."""

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
        task = client.cancel_task(task_id)
    except APIError as e:
        handle_api_error(e)
        return

    task["cancel_reason"] = reason
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
