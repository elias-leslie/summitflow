"""Subtask validation helpers."""

from __future__ import annotations

from typing import Any

import typer


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


def validate_steps_input(
    steps_json: str | None, steps: list[str] | None
) -> list[dict[str, Any]] | list[str]:
    """Validate and return steps from either JSON or legacy format.

    Args:
        steps_json: JSON string containing array of step objects
        steps: Legacy list of step descriptions

    Returns:
        Validated steps list

    Raises:
        typer.Exit: If validation fails
    """
    from ..output import output_error

    if steps_json:
        return parse_json_steps(steps_json)
    if steps:
        output_error(
            "Warning: --step creates steps as plain descriptions. "
            "Use --steps-json for structured step objects."
        )
        return steps

    output_error(
        "Steps are required. Use --steps-json with description "
        "on each step."
    )
    raise typer.Exit(1)


def parse_json_steps(steps_json: str) -> list[dict[str, Any]]:
    """Parse and validate JSON steps.

    Args:
        steps_json: JSON string containing array of step objects

    Returns:
        List of validated step dictionaries

    Raises:
        typer.Exit: If validation fails
    """
    import json

    from ..output import output_error

    try:
        parsed = json.loads(steps_json)
        if not isinstance(parsed, list):
            output_error("--steps-json must be a JSON array")
            raise typer.Exit(1)

        for i, step in enumerate(parsed):
            validate_step_object(step, i + 1)

        return parsed
    except json.JSONDecodeError as e:
        output_error(f"Invalid JSON in --steps-json: {e}")
        raise typer.Exit(1) from None


def validate_step_object(step: Any, index: int) -> None:
    """Validate a single step object.

    Args:
        step: Step object to validate
        index: Step number for error messages

    Raises:
        typer.Exit: If validation fails
    """
    from ..output import output_error

    if not isinstance(step, dict):
        output_error(f"Step {index}: must be object, not {type(step).__name__}")
        raise typer.Exit(1)
    if not step.get("description"):
        output_error(f"Step {index}: missing required 'description'")
        raise typer.Exit(1)
