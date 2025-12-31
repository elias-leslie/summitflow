"""Dependency commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import output_deps, output_error, output_success

app = typer.Typer(help="Dependency management commands")


def _handle_api_error(e: APIError) -> None:
    """Handle API error and exit."""
    output_error(e.detail)
    raise typer.Exit(1)


@app.command()
def add(
    task_id: str,
    depends_on: str,
    dep_type: Annotated[str, typer.Option("-t", "--type")] = "blocks",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Add a dependency to a task.

    Examples:
        st dep add task-abc123 task-def456 --type blocks
        st dep add task-abc123 task-def456 --type discovered-from
    """
    client = STClient()

    try:
        dep = client.add_dependency(task_id, depends_on, dep_type)
    except APIError as e:
        _handle_api_error(e)
        return

    if json_output:
        from ..output import output_json

        output_json(dep)
    else:
        output_success(f"Added dependency: {task_id} {dep_type} {depends_on}")


@app.command("list")
def list_deps(
    task_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List dependencies for a task.

    Examples:
        st dep list task-abc123
        st dep list task-abc123 --json
    """
    client = STClient()

    try:
        deps = client.list_dependencies(task_id)
    except APIError as e:
        _handle_api_error(e)
        return

    output_deps(deps, json_output)


@app.command()
def rm(
    task_id: str,
    depends_on: str,
    dep_type: Annotated[str | None, typer.Option("-t", "--type")] = None,
) -> None:
    """Remove a dependency from a task.

    Examples:
        st dep rm task-abc123 task-def456
        st dep rm task-abc123 task-def456 --type blocks
    """
    client = STClient()

    try:
        result = client.remove_dependency(task_id, depends_on, dep_type)
    except APIError as e:
        _handle_api_error(e)
        return

    if result.get("status") == "removed":
        output_success(f"Removed dependency: {task_id} -> {depends_on}")
    else:
        output_error("Dependency not found")
        raise typer.Exit(1)
