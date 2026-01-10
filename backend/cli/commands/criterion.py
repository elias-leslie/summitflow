"""Criterion commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error, output_json

app = typer.Typer(help="Criterion management commands")


@app.command("list")
def list_criteria(
    capability_id: Annotated[
        str | None, typer.Option("--capability", "-c", help="Capability ID")
    ] = None,
    task_id: Annotated[str | None, typer.Option("--task", "-t", help="Task ID")] = None,
) -> None:
    """List criteria for a capability or task.

    Must provide either --capability or --task.

    Examples:
        st criterion list --capability user-login
        st criterion list --task task-abc123
        st criterion list -t task-abc123
    """
    if not capability_id and not task_id:
        output_error("Must provide --capability or --task")
        raise typer.Exit(1)

    if capability_id and task_id:
        output_error("Cannot provide both --capability and --task")
        raise typer.Exit(1)

    client = STClient()

    try:
        if capability_id:
            criteria = client.list_criteria(capability_id)
        else:
            criteria = client.list_task_criteria(task_id)  # type: ignore
    except APIError as e:
        handle_api_error(e)
        return

    output_json(criteria)


@app.command("create")
def create_criterion(
    criterion: Annotated[str, typer.Argument(help="Criterion text (min 10 chars)")],
    capability_id: Annotated[str, typer.Option("--capability", "-c", help="Capability to link")],
    category: Annotated[
        str, typer.Option("--category", help="correctness, performance, security, quality")
    ] = "correctness",
    measurement: Annotated[
        str, typer.Option("--measurement", "-m", help="test, metric, tool, manual")
    ] = "test",
    threshold: Annotated[
        str | None, typer.Option("--threshold", "-t", help="Threshold value e.g., '<200ms'")
    ] = None,
) -> None:
    """Create a criterion and link to a capability.

    Examples:
        st criterion create "API response time under 200ms" --capability api-performance --category performance --threshold "<200ms"
        st criterion create "All tests pass" -c task-tracking
    """
    client = STClient()

    try:
        result = client.create_criterion(
            capability_id=capability_id,
            criterion=criterion,
            category=category,
            measurement=measurement,
            threshold=threshold,
        )
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)


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
) -> None:
    """Update a criterion.

    Examples:
        st criterion update ac-001 --criterion "Updated criterion text"
        st criterion update ac-001 --category performance --threshold "<100ms"
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
