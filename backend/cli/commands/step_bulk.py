"""Bulk step operations: add multiple steps at once."""

from __future__ import annotations

import json
from typing import Any

import typer

from ..client import APIError, STClient
from ..context import require_task_id
from ..output import handle_api_error, output_success


def add_steps(
    subtask_id: str,
    descriptions: list[str] | None = None,
    verify_command: str | None = None,
    expected_output: str | None = None,
    json_input: str | None = None,
    task_id: str | None = None,
) -> None:
    """Add steps to a subtask (verification required).

    Each step must have a verify_command and expected_output.

    Two modes:
    1. Positional descriptions with shared -v/-e (all steps get same verification):
       st step add 1.1 "Step 1" "Step 2" -v "dt pytest" -e "All pass"

    2. JSON for per-step verification:
       st step add 1.1 --json '[{"description":"...","verify_command":"...","expected_output":"..."}]'

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step add 1.1 "Add endpoint" -v "rg 'def foo' api.py" -e "Found" -t task-abc123
        st step add 1.1 --json '[{"description":"Run tests","verify_command":"dt pytest","expected_output":"passed"}]'
    """
    task_id = require_task_id(task_id)
    client = STClient()

    steps_to_create = _parse_step_input(
        descriptions, verify_command, expected_output, json_input
    )

    created_count = 0
    first_step_num = None
    for step in steps_to_create:
        try:
            result = client.create_step_with_verification(
                task_id,
                subtask_id,
                step["description"],
                step["verify_command"],
                step["expected_output"],
            )
            created_count += 1
            if first_step_num is None:
                first_step_num = result.get("step_number", "?")
        except APIError as e:
            handle_api_error(e)
            return

    output_success(f"{subtask_id}|+{created_count} from {first_step_num}")


def _parse_step_input(
    descriptions: list[str] | None,
    verify_command: str | None,
    expected_output: str | None,
    json_input: str | None,
) -> list[dict[str, str]]:
    """Parse and validate step input from either JSON or positional args."""
    if json_input is not None:
        return _parse_json_input(json_input, descriptions)

    if descriptions:
        return _parse_positional_input(descriptions, verify_command, expected_output)

    typer.echo("Error: provide step descriptions or --json input.", err=True)
    raise typer.Exit(1)


def _parse_json_input(
    json_input: str,
    descriptions: list[str] | None,
) -> list[dict[str, str]]:
    """Parse JSON input for steps."""
    if descriptions:
        typer.echo("Error: provide positional descriptions OR --json, not both.", err=True)
        raise typer.Exit(1)

    try:
        parsed = json.loads(json_input)
    except json.JSONDecodeError as e:
        typer.echo(f"Error: invalid JSON: {e}", err=True)
        raise typer.Exit(1) from None

    if not isinstance(parsed, list):
        typer.echo("Error: --json must be a JSON array.", err=True)
        raise typer.Exit(1)

    steps: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            typer.echo("Error: each --json element must be an object.", err=True)
            raise typer.Exit(1)

        _validate_json_step(item)
        steps.append({
            "description": item["description"],
            "verify_command": item["verify_command"],
            "expected_output": item["expected_output"],
        })

    return steps


def _validate_json_step(item: dict[str, Any]) -> None:
    """Validate a single JSON step has required fields."""
    missing = [
        k for k in ("description", "verify_command", "expected_output") if k not in item
    ]
    if missing:
        typer.echo(f"Error: JSON element missing keys: {', '.join(missing)}", err=True)
        raise typer.Exit(1)


def _parse_positional_input(
    descriptions: list[str],
    verify_command: str | None,
    expected_output: str | None,
) -> list[dict[str, str]]:
    """Parse positional description input with shared verification."""
    if verify_command is None or expected_output is None:
        typer.echo(
            "Error: -v (verify) and -e (expected) are required.\n"
            "  Every step needs verification. Use --json for per-step verify commands.",
            err=True,
        )
        raise typer.Exit(1)

    return [
        {
            "description": desc,
            "verify_command": verify_command,
            "expected_output": expected_output,
        }
        for desc in descriptions
    ]
