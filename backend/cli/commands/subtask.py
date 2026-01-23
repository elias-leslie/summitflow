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
    steps_json: Annotated[
        str | None,
        typer.Option("--steps-json", help="JSON array of step objects with verify_command"),
    ] = None,
) -> None:
    """Create a subtask for a task.

    If no task_id is provided, uses the active context from 'st work'.

    Steps must be provided with verify_command and expected_output.
    Use --steps-json for full step objects, or --step for simple descriptions (legacy).

    Examples:
        st subtask create 1.1 -d "Add component" --task task-abc123 \\
          --steps-json '[{"description": "Do X", "verify_command": "echo ok", "expected_output": "ok"}]'
    """
    import json

    from ..context import require_task_id

    task_id = require_task_id(task_id)

    # Validate steps - must have verify_command and expected_output
    final_steps: list[dict] | list[str] | None = None

    if steps_json:
        try:
            parsed_steps = json.loads(steps_json)
            if not isinstance(parsed_steps, list):
                output_error("--steps-json must be a JSON array")
                raise typer.Exit(1)

            # Validate each step has required fields
            for i, step in enumerate(parsed_steps):
                if not isinstance(step, dict):
                    output_error(f"Step {i + 1}: must be object, not {type(step).__name__}")
                    raise typer.Exit(1)
                if not step.get("verify_command"):
                    output_error(f"Step {i + 1}: missing required 'verify_command'")
                    raise typer.Exit(1)
                if not step.get("expected_output"):
                    output_error(f"Step {i + 1}: missing required 'expected_output'")
                    raise typer.Exit(1)

            final_steps = parsed_steps
        except json.JSONDecodeError as e:
            output_error(f"Invalid JSON in --steps-json: {e}")
            raise typer.Exit(1) from None
    elif steps:
        # Legacy string steps - warn but allow (API will create steps without verify_command)
        output_error(
            "Warning: --step creates steps without verify_command. "
            "Use --steps-json for proper step structure."
        )
        final_steps = steps

    if not final_steps:
        output_error(
            "Steps are required. Use --steps-json with verify_command and expected_output "
            "on each step."
        )
        raise typer.Exit(1)

    client = STClient()

    try:
        client.create_subtask(
            task_id=task_id,
            subtask_id=subtask_id,
            description=description,
            phase=phase,
            steps=final_steps,
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
                # Build map of step_number -> passes for fix step lookups
                step_passes = {s["step_number"]: s.get("passes", False) for s in steps_from_table}

                def is_step_resolved(step: dict) -> bool:
                    """Check if a step is resolved (passed or plan_defect with passing fix)."""
                    if step.get("passes"):
                        return True
                    # plan_defect steps are resolved if their fix step passed
                    if step.get("status") == "plan_defect":
                        fix_num = step.get("fix_step_number")
                        if fix_num and step_passes.get(fix_num, False):
                            return True
                    return False

                incomplete = [s["step_number"] for s in steps_from_table if not is_step_resolved(s)]
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
