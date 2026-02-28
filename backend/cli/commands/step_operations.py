"""Core step operations: pass, new, update, delete."""

from __future__ import annotations

from typing import Any

import typer

from ..client import APIError, STClient
from ..context import require_task_id
from ..output import handle_api_error, output_success


def pass_step(
    subtask_id: str,
    step_number: int,
    task_id: str | None = None,
) -> None:
    """Mark a step as passed.

    Examples:
        st step pass 1.1 1 --task task-abc123
        st step pass 1.1 1    # Uses active context
    """
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.update_step(task_id, subtask_id, step_number, passes=True)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"{subtask_id}.{step_number}")


def new_step(
    subtask_id: str,
    description: str,
    task_id: str | None = None,
) -> None:
    """Create a single step.

    Examples:
        st step new 1.1 "Add login endpoint" --task task-abc123
        st step new 1.1 "Run tests"    # Uses active context
    """
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        result = client.create_step_with_verification(
            task_id, subtask_id, description
        )
    except APIError as e:
        handle_api_error(e)
        return

    step_num = result.get("step_number", "?")
    output_success(f"{subtask_id}.{step_num}")


def update_step(
    subtask_id: str,
    step_number: int,
    description: str | None = None,
    task_id: str | None = None,
) -> None:
    """Update step description.

    Examples:
        st step update 1.1 1 -d "Clearer description" --task task-abc123
        st step update 1.1 1 -d "Clearer description"    # Uses active context
    """
    if not description:
        typer.echo("Error: --desc/-d is required", err=True)
        raise typer.Exit(1)

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.update_step_fields(
            task_id,
            subtask_id,
            step_number,
            description=description,
        )
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"{subtask_id}.{step_number}")


def delete_step(
    subtask_id: str,
    step_number: int,
    task_id: str | None = None,
    force: bool = False,
) -> None:
    """Delete a step from a subtask.

    If the step has already passed, --force is required.

    Examples:
        st step delete 1.1 3 --task task-abc123
        st step delete 1.1 3             # Uses active context
        st step delete 1.1 3 --force     # Force delete passed step
    """
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        result = client.delete_step(task_id, subtask_id, step_number, force=force)
    except APIError as e:
        detail: dict[str, Any] = e.detail if isinstance(e.detail, dict) else {}
        if detail.get("requires_force"):
            _error_force_required(subtask_id, step_number)
        handle_api_error(e)
        return

    _show_deletion_result(result, subtask_id, step_number)


def _error_force_required(subtask_id: str, step_number: int) -> None:
    """Show error for force-required deletion."""
    typer.echo(
        f"BLOCKED: Step {subtask_id}.{step_number} has passed.\n"
        f"  Use --force to delete (will invalidate subtask passes status).",
        err=True,
    )
    raise typer.Exit(1) from None


def _show_deletion_result(
    result: dict[str, Any],
    subtask_id: str,
    step_number: int,
) -> None:
    """Show deletion result with audit info."""
    was_passed = result.get("was_passed", False)
    subtask_invalidated = result.get("subtask_invalidated", False)

    if subtask_invalidated:
        typer.echo(
            f"DEL {subtask_id}.{step_number} (was passed, subtask invalidated)",
            err=True,
        )
    elif was_passed:
        typer.echo(f"DEL {subtask_id}.{step_number} (was passed)")
    else:
        print(f"DEL {subtask_id}.{step_number}")
