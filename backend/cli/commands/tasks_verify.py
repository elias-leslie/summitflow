"""Task plan verification command."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ..client import APIError, STClient
from ..output import output_error
from .tasks_validation import validate_plan_schema


def verify_plan_file(
    file_path: Path,
    client: STClient,
) -> None:
    """Verify a plan.json file against the schema."""
    import jsonschema as js

    try:
        content = file_path.read_text()
        plan = json.loads(content)
    except FileNotFoundError:
        output_error(f"File not found: {file_path}")
        raise typer.Exit(1) from None
    except json.JSONDecodeError as e:
        output_error(f"Invalid JSON at line {e.lineno}: {e.msg}")
        raise typer.Exit(1) from None

    # Fetch schema from API
    try:
        schema = client.get(f"{client.base_url}/schemas/plan")
    except APIError as e:
        output_error(f"Failed to fetch schema: {e.detail}")
        raise typer.Exit(1) from None

    # Validate against JSON schema
    issues: list[str] = []
    try:
        js.validate(plan, schema)
    except js.ValidationError as e:
        path = ".".join(str(p) for p in e.absolute_path) if e.absolute_path else "root"
        issues.append(f"Schema: {path}: {e.message}")

    # Validate plan structure
    issues.extend(validate_plan_schema(plan))

    # Output result
    if issues:
        typer.echo("FAIL")
        for issue in issues:
            typer.echo(f"  - {issue}", err=True)
        raise typer.Exit(1)
    else:
        complexity = plan.get("complexity", "SIMPLE")
        typer.echo("PASS")
        typer.echo(f"  complexity: {complexity}")
        typer.echo(f"  subtasks: {len(plan.get('subtasks', []))}")
        if plan.get("done_when"):
            typer.echo(f"  done_when: {len(plan['done_when'])} items")
