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


@app.command("delete")
def delete_step(
    task_id: str,
    subtask_id: str,
    step_number: int,
) -> None:
    """Delete a step from a subtask.

    Examples:
        st step delete task-abc123 1.1 3
    """
    client = STClient()

    try:
        client.delete_step(task_id, subtask_id, step_number)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"Deleted step {step_number} from subtask {subtask_id}")


@app.command("insert")
def insert_step(
    task_id: str,
    subtask_id: str,
    position: int,
    description: str,
) -> None:
    """Insert a step at a specific position, shifting existing steps down.

    Use this to add work before an incomplete step. All steps at the
    insertion position and after are renumbered (incremented by 1).

    Examples:
        st step insert task-abc123 1.1 3 "Complete dark mode cleanup"
        st step insert task-abc123 2.1 7 "INCOMPLETE: Fix validation"
    """
    client = STClient()

    try:
        result = client.insert_step(task_id, subtask_id, position, description)
    except APIError as e:
        handle_api_error(e)
        return

    step_num = result.get("step_number", position)
    output_success(f"Inserted step {step_num} into subtask {subtask_id}")
