"""Subtask commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import (
    handle_api_error,
    output_error,
    output_json,
    output_subtasks,
    output_success,
)

app = typer.Typer(help="Subtask management commands")


@app.command("list")
def list_subtasks(
    task_id: Annotated[str | None, typer.Argument()] = None,
) -> None:
    """List subtasks for a task with progress.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st subtask list task-abc123
        st subtask list    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        result = client.get_subtasks(task_id, include_steps=True)
    except APIError as e:
        handle_api_error(e)
        return

    subtasks = result.get("subtasks", [])
    summary = result.get("summary", {})

    output_subtasks(subtasks, summary)


@app.command("show")
def show_subtask(
    subtask_id: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Show details of a specific subtask.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st subtask show 1.1 --task task-abc123
        st subtask show 1.1    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        result = client.get_subtasks(task_id, include_steps=True)
    except APIError as e:
        handle_api_error(e)
        return

    subtasks = result.get("subtasks", [])
    target = None
    for s in subtasks:
        if s.get("subtask_id") == subtask_id:
            target = s
            break

    if target is None:
        output_error(f"Subtask {subtask_id} not found for task {task_id}")
        raise typer.Exit(1)

    output_json(target)


@app.command("create")
def create_subtask(
    subtask_id: str,
    description: Annotated[str, typer.Option("-d", "--description")],
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
    phase: Annotated[str, typer.Option("--phase")] = "implementation",
    steps: Annotated[list[str] | None, typer.Option("--step")] = None,
) -> None:
    """Create a subtask for a task.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st subtask create 1.1 -d "Add component" --task task-abc123
        st subtask create 1.1 -d "Add component" --step "Step 1" --step "Step 2"
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.create_subtask(
            task_id=task_id,
            subtask_id=subtask_id,
            description=description,
            phase=phase,
            steps=steps,
        )
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"Created subtask {subtask_id} for task {task_id}")


@app.command("pass")
def pass_subtask(
    subtask_id: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Mark a subtask as passed.

    All steps must be complete before passing (enforced by DB trigger).
    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st subtask pass 1.1 --task task-abc123
        st subtask pass 1.1    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    # Pre-check: verify all steps are complete
    try:
        result = client.get_subtasks(task_id, include_steps=True)
        subtasks = result.get("subtasks", [])
        target = None
        for s in subtasks:
            if s.get("subtask_id") == subtask_id:
                target = s
                break

        if target:
            steps_from_table = target.get("steps_from_table", [])
            if steps_from_table:
                incomplete = [s["step_number"] for s in steps_from_table if not s.get("passes")]
                if incomplete:
                    output_error(
                        f"Incomplete steps: {', '.join(map(str, incomplete))}. "
                        f"Complete with: st step pass {task_id} {subtask_id} <step#>"
                    )
                    raise typer.Exit(1)
    except APIError:
        pass  # Continue - let API handle any errors

    try:
        client.update_subtask(task_id, subtask_id, passes=True)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"Marked subtask {subtask_id} as passed")


@app.command("delete")
def delete_subtask(
    subtask_id: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Delete a subtask and all its steps.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st subtask delete 99.1 --task task-abc123
        st subtask delete 99.1    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.delete_subtask(task_id, subtask_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"Deleted subtask {subtask_id} from task {task_id}")
