"""Active task context for CLI.

Commands use require_task_id() to resolve task_id from argument or environment.
"""

from __future__ import annotations

import os

from app.storage.tasks import canonicalize_task_id


def require_task_id(explicit_task_id: str | None) -> str:
    """Get task_id from argument or ST_CURRENT_TASK_ID env var.

    Args:
        explicit_task_id: Task ID passed as argument (takes priority)

    Returns:
        Task ID from argument or environment

    Raises:
        typer.Exit: If no task_id available
    """
    import typer

    from .output import output_error

    if explicit_task_id:
        return canonicalize_task_id(explicit_task_id)

    env_task = os.getenv("ST_CURRENT_TASK_ID")
    if env_task:
        return canonicalize_task_id(env_task)

    output_error(
        "No task specified and no active context.\nEither provide a task_id or use -t/--task flag."
    )
    raise typer.Exit(1)
