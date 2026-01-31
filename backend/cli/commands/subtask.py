"""Subtask commands for the CLI."""

from __future__ import annotations

from typing import Annotated, Any, cast

import typer

from ..client import APIError, STClient
from ..output import (
    handle_api_error,
    output_error,
    output_success,
)

app = typer.Typer(help="Subtask management commands")


def is_step_resolved(step: dict[str, Any], step_passes: dict[int, bool]) -> bool:
    """Check if a step is resolved (passed or plan_defect with passing fix).

    A step is considered resolved if:
    1. It has passes=True, OR
    2. It has status="plan_defect" AND its linked fix_step_number has passes=True

    Args:
        step: Step data dict with 'passes', 'status', and 'fix_step_number' fields
        step_passes: Map of step_number -> passes for all steps in the subtask

    Returns:
        True if the step is resolved, False otherwise
    """
    if step.get("passes"):
        return True
    # plan_defect steps are resolved if their fix step passed
    if step.get("status") == "plan_defect":
        fix_num = step.get("fix_step_number")
        if fix_num and step_passes.get(fix_num, False):
            return True
    return False


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
    final_steps: list[dict[str, Any]] | list[str] | None = None

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
            steps=cast(list[str | dict[str, Any]] | None, final_steps),
        )
    except APIError as e:
        handle_api_error(e)
        return

    output_success(subtask_id)


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
                step_passes_map = {
                    s["step_number"]: s.get("passes", False) for s in steps_from_table
                }

                incomplete = [
                    s["step_number"]
                    for s in steps_from_table
                    if not is_step_resolved(s, step_passes_map)
                ]
                if incomplete:
                    output_error(f"INCOMPLETE:{subtask_id}|steps:{','.join(map(str, incomplete))}")
                    raise typer.Exit(1)
    except APIError:
        pass  # Continue - let API handle any errors

    try:
        client.update_subtask(task_id, subtask_id, passes=True)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(subtask_id)


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

    print(f"DEL {subtask_id}")


@app.command("citations")
def log_citations_cmd(
    citations: Annotated[
        list[str] | None,
        typer.Argument(help="Citations in suffix notation (M:abc123+ G:def456-)"),
    ] = None,
    subtask_id: Annotated[str | None, typer.Option("--subtask", "-s", help="Subtask ID")] = None,
    task_id: Annotated[str | None, typer.Option("--task", "-t", help="Task ID")] = None,
    none: Annotated[bool, typer.Option("--none", help="Confirm no memories were needed")] = False,
) -> None:
    """Log episode citations with suffix notation ratings.

    Citations use suffix notation for three-signal rating:
    - M:abc12345+  -> mandate helpful (promotes episode)
    - G:def67890-  -> guardrail harmful (demotes episode)
    - M:xyz99999   -> used/neutral (no suffix)

    Use --none ONLY if you have honestly reflected and determined that none of
    the injected memories in <memory-context> were applicable to this subtask.
    If ANY memory helped guide your approach, cite it instead.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st subtask citations M:abc12345+ G:def67890- --subtask 1.1
        st subtask citations M:85bf4635+ -s 2.1
        st subtask citations --none -s 1.1  # Only if truly no memories helped
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    if not subtask_id:
        output_error("Subtask ID required (--subtask/-s)")
        raise typer.Exit(1)

    if none and citations:
        output_error("Cannot use --none with citations. Choose one.")
        raise typer.Exit(1)

    if not none and not citations:
        output_error("Provide citations or use --none to confirm none were needed.")
        raise typer.Exit(1)

    client = STClient()

    if none:
        try:
            result = client.acknowledge_no_citations(task_id, subtask_id)
        except APIError as e:
            handle_api_error(e)
            return

        if result.get("acknowledged"):
            output_success(
                f"Confirmed: no memories from <memory-context> applied to subtask {subtask_id}. "
                "If this is incorrect, cite the relevant memories now."
            )
        else:
            output_error("Failed to acknowledge")
            raise typer.Exit(1)
    else:
        assert citations is not None
        try:
            result = client.log_citations(task_id, subtask_id, citations)
        except APIError as e:
            handle_api_error(e)
            return

        logged = result.get("logged", 0)
        output_success(f"Logged {logged} citations for subtask {subtask_id}")


# Error stubs for removed commands - provide helpful redirects
@app.command("list", hidden=True)
def list_removed() -> None:
    """Removed: use st context instead."""
    typer.echo("Command 'subtask list' has been removed.\n", err=True)
    typer.echo("Use instead:", err=True)
    typer.echo("  st context <task-id>    - Shows all subtasks with steps", err=True)
    raise typer.Exit(1)


@app.command("show", hidden=True)
def show_removed() -> None:
    """Removed: use st context --subtask instead."""
    typer.echo("Command 'subtask show' has been removed.\n", err=True)
    typer.echo("Use instead:", err=True)
    typer.echo("  st context <task-id> --subtask X.Y    - Subtask-scoped context", err=True)
    raise typer.Exit(1)
