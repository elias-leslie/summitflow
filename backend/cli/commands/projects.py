"""Project management commands for the CLI."""

from __future__ import annotations

import logging
import os
from typing import Annotated

import typer

from ..config import get_config
from ..output import output_json
from ._projects_helpers import (
    DEFAULT_HEALTH_ENDPOINT,
    ENV_PROJECT_ID,
    projects_api,
    run_create,
    run_delete,
    run_list,
    run_update,
)

logger = logging.getLogger(__name__)

app = typer.Typer(help="Project management commands")


@app.callback(invoke_without_command=True)
def projects_default(ctx: typer.Context) -> None:
    """List all registered projects."""
    if ctx.invoked_subcommand is None:
        list_projects()


@app.command("list")
def list_projects(
    verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False,
) -> None:
    """List all registered projects.

    Shows project ID, name, and root path. The current project
    (based on working directory) is marked with an asterisk.

    Examples:
        st projects list
        st projects list -v
    """
    run_list(verbose=verbose)


@app.command()
def current() -> None:
    """Show the current project (based on working directory or ST_PROJECT_ID).

    Examples:
        st projects current
    """
    try:
        config = get_config()
        output_json(
            {
                "project_id": config.project_id,
                "project_root": config.project_root,
                "api_base": config.api_base,
                "source": (
                    ENV_PROJECT_ID if os.getenv(ENV_PROJECT_ID) else "auto-detected from cwd"
                ),
            }
        )
    except SystemExit:
        raise


@app.command("get")
def get_project(
    project_id: Annotated[str, typer.Argument(help="Project ID to retrieve")],
) -> None:
    """Get a single project by ID.

    Examples:
        st projects get summitflow
        st projects get agent-hub
    """
    result = projects_api("GET", f"/{project_id}")
    output_json(result)


@app.command("create")
def create_project(
    project_id: Annotated[str, typer.Argument(help="Unique project ID (slug)")],
    name: Annotated[str, typer.Argument(help="Display name for the project")],
    base_url: Annotated[str, typer.Option("--base-url", "-u", help="Base URL for the project API")],
    root_path: Annotated[
        str | None,
        typer.Option("--root-path", "-r", help="Filesystem root path for the project"),
    ] = None,
    health_endpoint: Annotated[
        str,
        typer.Option("--health-endpoint", help="Health check endpoint path"),
    ] = DEFAULT_HEALTH_ENDPOINT,
) -> None:
    """Create a new project.

    Examples:
        st projects create persona-sandbox "Persona Sandbox" --base-url http://localhost:3003
        st projects create my-app "My App" -u http://localhost:8080 -r /home/user/my-app
    """
    run_create(project_id, name, base_url, root_path, health_endpoint)


@app.command("update")
def update_project(
    project_id: Annotated[str, typer.Argument(help="Project ID to update")],
    name: Annotated[str | None, typer.Option("--name", "-n", help="New display name")] = None,
    base_url: Annotated[str | None, typer.Option("--base-url", "-u", help="New base URL")] = None,
    root_path: Annotated[
        str | None, typer.Option("--root-path", "-r", help="New filesystem root path")
    ] = None,
    health_endpoint: Annotated[
        str | None, typer.Option("--health-endpoint", help="New health check endpoint")
    ] = None,
) -> None:
    """Update an existing project. At least one field must be provided.

    Examples:
        st projects update persona-sandbox --name "Persona Sandbox v2"
        st projects update my-app --base-url http://localhost:9090 --root-path /new/path
    """
    run_update(project_id, name, base_url, root_path, health_endpoint)


@app.command("delete")
def delete_project(
    project_id: Annotated[str, typer.Argument(help="Project ID to delete")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Required to confirm deletion"),
    ] = False,
) -> None:
    """Delete a project. Requires --force flag to confirm deletion.

    Examples:
        st projects delete persona-sandbox         # shows what would be deleted
        st projects delete persona-sandbox --force  # actually deletes
    """
    run_delete(project_id, force=force)
