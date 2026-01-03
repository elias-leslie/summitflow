"""Dependency commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_deps, output_json

app = typer.Typer(help="Dependency management commands")


@app.command()
def add(
    task_id: str,
    depends_on: str,
    dep_type: Annotated[str, typer.Option("-t", "--type")] = "blocks",
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
        handle_api_error(e)
        return

    output_json(dep)


@app.command("list")
def list_deps(
    task_id: str,
) -> None:
    """List dependencies for a task.

    Examples:
        st dep list task-abc123
    """
    client = STClient()

    try:
        deps = client.list_dependencies(task_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_deps(deps)


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
        handle_api_error(e)
        return

    output_json(result)
