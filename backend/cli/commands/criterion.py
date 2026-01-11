"""Criterion commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error, output_json

app = typer.Typer(help="Criterion management commands")


@app.command("list")
def list_criteria(
    task_id: Annotated[str, typer.Option("--task", "-t", help="Task ID")],
) -> None:
    """List criteria for a task.

    Examples:
        st criterion list --task task-abc123
        st criterion list -t task-abc123
    """
    client = STClient()

    try:
        criteria = client.list_task_criteria(task_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(criteria)


@app.command("create")
def create_criterion(
    criterion: Annotated[str, typer.Argument(help="Criterion text (min 10 chars)")],
    task_id: Annotated[str | None, typer.Option("--task", "-t", help="Task ID to link")] = None,
    category: Annotated[
        str, typer.Option("--category", help="correctness, performance, security, quality")
    ] = "correctness",
    verify_command: Annotated[
        str | None, typer.Option("--verify-command", "-v", help="Bash command to verify")
    ] = None,
    verify_by: Annotated[
        str, typer.Option("--verify-by", help="Verification method: test, agent, human, opus")
    ] = "test",
    expected_output: Annotated[
        str | None, typer.Option("--expected-output", "-e", help="Expected output for verification")
    ] = None,
) -> None:
    """Create a criterion and link to a task.

    Examples:
        st criterion create "All pytest tests pass" --task task-abc123 --verify-by test
        st criterion create "UI renders correctly" -t task-abc123 --verify-by agent -v "ba check http://localhost:3001 --no-errors"
    """
    if not task_id:
        output_error("--task is required")
        raise typer.Exit(1)

    client = STClient()

    criterion_data = {
        "criterion": criterion,
        "category": category,
        "verify_by": verify_by,
    }
    if verify_command:
        criterion_data["verify_command"] = verify_command
    if expected_output:
        criterion_data["expected_output"] = expected_output

    try:
        result = client.batch_create_task_criteria(task_id, [criterion_data])
    except APIError as e:
        handle_api_error(e)
        return

    # Return the created criterion (first item from batch)
    if result.get("created"):
        output_json(result["created"][0])
    else:
        output_error(f"Failed to create criterion: {result.get('errors', 'Unknown error')}")
        raise typer.Exit(1)


@app.command("update")
def update_criterion(
    criterion_id: str,
    criterion: Annotated[str | None, typer.Option("--criterion", help="New criterion text")] = None,
    category: Annotated[str | None, typer.Option("--category", help="New category")] = None,
    measurement: Annotated[
        str | None, typer.Option("--measurement", "-m", help="New measurement type")
    ] = None,
    threshold: Annotated[
        str | None, typer.Option("--threshold", "-t", help="New threshold value")
    ] = None,
    verify_command: Annotated[
        str | None, typer.Option("--verify-command", "-v", help="Bash command to verify")
    ] = None,
    verify_by: Annotated[
        str | None,
        typer.Option("--verify-by", help="Verification method: test, agent, human, opus"),
    ] = None,
    expected_output: Annotated[
        str | None, typer.Option("--expected-output", "-e", help="Expected output for verification")
    ] = None,
) -> None:
    """Update a criterion.

    Examples:
        st criterion update ac-001 --criterion "Updated criterion text"
        st criterion update ac-001 --category performance --threshold "<100ms"
        st criterion update ac-001 --verify-command "ba check http://localhost:3001 --no-errors"
        st criterion update ac-001 --verify-by agent --expected-output "Screenshot shows 5 columns"
    """
    client = STClient()

    # Build update dict
    updates: dict = {}
    if criterion is not None:
        updates["criterion"] = criterion
    if category is not None:
        updates["category"] = category
    if measurement is not None:
        updates["measurement"] = measurement
    if threshold is not None:
        updates["threshold"] = threshold
    if verify_command is not None:
        updates["verify_command"] = verify_command
    if verify_by is not None:
        updates["verify_by"] = verify_by
    if expected_output is not None:
        updates["expected_output"] = expected_output

    if not updates:
        output_error("No updates specified")
        raise typer.Exit(1)

    try:
        result = client.update_criterion(criterion_id, **updates)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)


@app.command("verify")
def verify_criterion(
    task_id: str,
    criterion_id: str,
    verified_by: Annotated[str, typer.Option("--by")] = "test",
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
        handle_api_error(e)
        return

    output_json(result)
