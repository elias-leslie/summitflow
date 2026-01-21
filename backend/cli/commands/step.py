"""Step commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_steps, output_success

app = typer.Typer(help="Step management commands")


@app.command("pass")
def pass_step(
    subtask_id: str,
    step_number: int,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Mark a step as passed.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step pass 1.1 1 --task task-abc123
        st step pass 1.1 1    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.update_step(task_id, subtask_id, step_number, passes=True)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"Marked step {step_number} of subtask {subtask_id} as passed")


@app.command("create")
def create_steps(
    subtask_id: str,
    descriptions: Annotated[list[str], typer.Argument()],
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Create steps for a subtask in batch.

    Pass multiple step descriptions as arguments.
    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step create 1.1 "Step 1" "Step 2" "Step 3" --task task-abc123
        st step create 1.1 "Step 1" "Step 2"    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
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
    subtask_id: str,
    descriptions: Annotated[list[str], typer.Argument()],
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Append steps to a subtask with existing steps.

    Unlike 'create' which starts at step 1, 'add' finds the highest
    existing step number and continues from there.
    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step add 1.1 "New step 6" "New step 7" --task task-abc123
        st step add 1.1 "New step 6" "New step 7"    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
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
    subtask_id: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """List steps for a subtask.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step list 1.1 --task task-abc123
        st step list 1.1    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        steps = client.get_steps(task_id, subtask_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_steps(steps, subtask_id)


@app.command("delete")
def delete_step(
    subtask_id: str,
    step_number: int,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Delete a step from a subtask.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step delete 1.1 3 --task task-abc123
        st step delete 1.1 3    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.delete_step(task_id, subtask_id, step_number)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"Deleted step {step_number} from subtask {subtask_id}")


@app.command("insert")
def insert_step(
    subtask_id: str,
    position: int,
    description: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Insert a step at a specific position, shifting existing steps down.

    Use this to add work before an incomplete step. All steps at the
    insertion position and after are renumbered (incremented by 1).
    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step insert 1.1 3 "Complete dark mode cleanup" --task task-abc123
        st step insert 1.1 3 "Complete dark mode cleanup"    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        result = client.insert_step(task_id, subtask_id, position, description)
    except APIError as e:
        handle_api_error(e)
        return

    step_num = result.get("step_number", position)
    output_success(f"Inserted step {step_num} into subtask {subtask_id}")
