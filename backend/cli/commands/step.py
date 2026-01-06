"""Step commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_steps, output_success

app = typer.Typer(help="Step management commands")


@app.command("pass")
def pass_step(
    task_id: str,
    subtask_id: str,
    step_number: int,
) -> None:
    """Mark a step as passed.

    Examples:
        st step pass task-abc123 1.1 1
    """
    client = STClient()

    try:
        client.update_step(task_id, subtask_id, step_number, passes=True)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"Marked step {step_number} of subtask {subtask_id} as passed")


@app.command("create")
def create_steps(
    task_id: str,
    subtask_id: str,
    descriptions: Annotated[list[str], typer.Argument()],
) -> None:
    """Create steps for a subtask in batch.

    Pass multiple step descriptions as arguments.

    Examples:
        st step create task-abc123 1.1 "Step 1" "Step 2" "Step 3"
    """
    client = STClient()

    try:
        result = client.bulk_create_steps(task_id, subtask_id, descriptions)
    except APIError as e:
        handle_api_error(e)
        return

    created = result.get("created", [])
    output_success(f"Created {len(created)} steps for subtask {subtask_id}")


@app.command("add")
def add_steps(
    task_id: str,
    subtask_id: str,
    descriptions: Annotated[list[str], typer.Argument()],
) -> None:
    """Append steps to a subtask with existing steps.

    Unlike 'create' which starts at step 1, 'add' finds the highest
    existing step number and continues from there.

    Examples:
        st step add task-abc123 1.1 "New step 6" "New step 7"
    """
    client = STClient()

    try:
        result = client.append_steps(task_id, subtask_id, descriptions)
    except APIError as e:
        handle_api_error(e)
        return

    created = result.get("created", [])
    if created:
        start_num = created[0].get("step_number", "?")
        output_success(
            f"Added {len(created)} steps to subtask {subtask_id} (starting at step {start_num})"
        )
    else:
        output_success("No steps added")


@app.command("list")
def list_steps(
    task_id: str,
    subtask_id: str,
) -> None:
    """List steps for a subtask.

    Examples:
        st step list task-abc123 1.1
    """
    client = STClient()

    try:
        steps = client.get_steps(task_id, subtask_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_steps(steps, subtask_id)
