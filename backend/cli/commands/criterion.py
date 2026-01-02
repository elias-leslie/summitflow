"""Criterion commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import output_error, output_json, output_success

app = typer.Typer(help="Criterion management commands")


def _handle_api_error(e: APIError) -> None:
    """Handle API error and exit."""
    output_error(e.detail)
    raise typer.Exit(1)


@app.command("verify")
def verify_criterion(
    task_id: str,
    criterion_id: str,
    verified_by: Annotated[str, typer.Option("--by")] = "test",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Verify a criterion for a task.

    Examples:
        st criterion verify task-abc123 ac-001
        st criterion verify task-abc123 ac-001 --by manual
    """
    client = STClient()

    try:
        result = client.verify_criterion(
            task_id=task_id,
            criterion_id=criterion_id,
            verified=True,
            verified_by=verified_by,
        )
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        output_json(result)
    else:
        output_success(f"Verified criterion {criterion_id} for task {task_id}")
