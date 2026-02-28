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
    json_input: str | None = None,
    task_id: str | None = None,
) -> None:
    """Add steps to a subtask.

    Two modes:
    1. Positional descriptions:
       st step add 1.1 "Step 1" "Step 2"

    2. JSON for structured input:
       st step add 1.1 --json '[{"description":"..."}]'

    Examples:
        st step add 1.1 "Add endpoint" -t task-abc123
        st step add 1.1 --json '[{"description":"Run tests"}]'
    """
    task_id = require_task_id(task_id)
    client = STClient()

    steps_to_create = _parse_step_input(descriptions, json_input)

    created_count = 0
    first_step_num = None
    for step in steps_to_create:
        try:
            result = client.create_step_with_verification(
                task_id,
                subtask_id,
                step["description"],
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
    json_input: str | None,
) -> list[dict[str, str]]:
    """Parse and validate step input from either JSON or positional args."""
    if json_input is not None:
        return _parse_json_input(json_input, descriptions)

    if descriptions:
        return [{"description": desc} for desc in descriptions]

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

        if "description" not in item:
            typer.echo("Error: JSON element missing key: description", err=True)
            raise typer.Exit(1)
        steps.append({"description": item["description"]})

    return steps
