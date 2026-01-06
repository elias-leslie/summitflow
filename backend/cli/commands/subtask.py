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
    task_id: str,
) -> None:
    """List subtasks for a task with progress.

    Examples:
        st subtask list task-abc123
    """
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
    task_id: str,
    subtask_id: str,
) -> None:
    """Show details of a specific subtask.

    Examples:
        st subtask show task-abc123 1.1
    """
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
    task_id: str,
    subtask_id: str,
    description: Annotated[str, typer.Option("-d", "--description")],
    phase: Annotated[str, typer.Option("--phase")] = "implementation",
    steps: Annotated[list[str] | None, typer.Option("--step")] = None,
) -> None:
    """Create a subtask for a task.

    Examples:
        st subtask create task-abc123 1.1 -d "Add component" --phase backend
        st subtask create task-abc123 1.1 -d "Add component" --step "Step 1" --step "Step 2"
    """
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
    task_id: str,
    subtask_id: str,
) -> None:
    """Mark a subtask as passed.

    Examples:
        st subtask pass task-abc123 1.1
    """
    client = STClient()

    try:
        client.update_subtask(task_id, subtask_id, passes=True)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"Marked subtask {subtask_id} as passed")


@app.command("delete")
def delete_subtask(
    task_id: str,
    subtask_id: str,
) -> None:
    """Delete a subtask and all its steps.

    Examples:
        st subtask delete task-abc123 99.1
    """
    client = STClient()

    try:
        client.delete_subtask(task_id, subtask_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"Deleted subtask {subtask_id} from task {task_id}")
