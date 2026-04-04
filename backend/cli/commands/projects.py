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
    run_onboard,
    run_root,
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


@app.command("root")
def get_project_root(
    project_id: Annotated[str, typer.Argument(help="Project ID to resolve")],
) -> None:
    """Print the canonical filesystem root for a project.

    Examples:
        st projects root summitflow
        st projects root terminal
    """
    run_root(project_id)


@app.command("create")
def create_project(
    project_id: Annotated[str, typer.Argument(help="Unique project ID (slug)")],
    name: Annotated[str, typer.Argument(help="Display name for the project")],
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", "-u", help="Base URL for the project API"),
    ] = None,
    root_path: Annotated[
        str | None,
        typer.Option("--root-path", "-r", help="Filesystem root path for the project"),
    ] = None,
    health_endpoint: Annotated[
        str,
        typer.Option("--health-endpoint", help="Health check endpoint path"),
    ] = DEFAULT_HEALTH_ENDPOINT,
    summitflow_hosted: Annotated[
        bool,
        typer.Option(
            "--summitflow-hosted",
            help="Derive the canonical hosted app URL and /srv/workspaces/projects/<project-id> defaults",
        ),
    ] = False,
    permission_tier: Annotated[
        str | None,
        typer.Option("--permission-tier", help="Bootstrap matching Agent Hub permission tier"),
    ] = None,
    auto_exec_enabled: Annotated[
        bool | None,
        typer.Option("--auto-exec/--no-auto-exec", help="Bootstrap Agent Hub auto-exec setting"),
    ] = None,
    execution_start_hour: Annotated[
        int | None,
        typer.Option("--execution-start-hour", min=0, max=23, help="Bootstrap Agent Hub execution window start hour"),
    ] = None,
    execution_end_hour: Annotated[
        int | None,
        typer.Option("--execution-end-hour", min=1, max=24, help="Bootstrap Agent Hub execution window end hour"),
    ] = None,
    onboard: Annotated[
        bool | None,
        typer.Option(
            "--onboard/--no-onboard",
            help="Queue standard SummitFlow onboarding (backups, scan, post-scan task sync). Defaults to on for --summitflow-hosted.",
        ),
    ] = None,
    backup_frequency: Annotated[
        str,
        typer.Option("--backup-frequency", help="Onboarding backup frequency"),
    ] = "daily",
    backup_retention_days: Annotated[
        int,
        typer.Option("--backup-retention-days", min=1, help="Onboarding backup retention in days"),
    ] = 30,
    initial_backup: Annotated[
        bool,
        typer.Option("--initial-backup/--no-initial-backup", help="Queue an initial baseline backup during onboarding"),
    ] = True,
) -> None:
    """Create a new project.

    Examples:
        st projects create persona-sandbox "Persona Sandbox" --base-url http://localhost:3003
        st projects create my-app "My App" -u http://localhost:8080 -r /home/user/my-app
        st projects create test2 "Testbed" --summitflow-hosted --permission-tier yolo --auto-exec
    """
    effective_onboard = summitflow_hosted if onboard is None else onboard

    run_create(
        project_id,
        name,
        base_url,
        root_path,
        health_endpoint,
        summitflow_hosted=summitflow_hosted,
        permission_tier=permission_tier,
        auto_exec_enabled=auto_exec_enabled,
        execution_start_hour=execution_start_hour,
        execution_end_hour=execution_end_hour,
        onboarding=effective_onboard,
        backup_frequency=backup_frequency,
        backup_retention_days=backup_retention_days,
        queue_initial_backup=initial_backup,
    )


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


@app.command("onboard")
def onboard_project(
    project_id: Annotated[str, typer.Argument(help="Project ID to onboard")],
    backup_frequency: Annotated[
        str,
        typer.Option("--backup-frequency", help="Standard backup frequency"),
    ] = "daily",
    backup_retention_days: Annotated[
        int,
        typer.Option("--backup-retention-days", min=1, help="Backup retention in days"),
    ] = 30,
    initial_backup: Annotated[
        bool,
        typer.Option("--initial-backup/--no-initial-backup", help="Queue an initial baseline backup when none exist"),
    ] = True,
) -> None:
    """Queue standard SummitFlow onboarding for an existing project.

    Examples:
        st projects onboard vantage
        st projects onboard test2 --no-initial-backup
    """
    run_onboard(
        project_id,
        backup_frequency=backup_frequency,
        backup_retention_days=backup_retention_days,
        queue_initial_backup=initial_backup,
    )


@app.command("delete")
def delete_project(
    project_id: Annotated[str, typer.Argument(help="Project ID to delete")],
    confirm: Annotated[
        str | None,
        typer.Option("--confirm", help="Confirm token from preview run"),
    ] = None,
) -> None:
    """Delete a project. Two-pass confirmation required.

    Examples:
        st projects delete persona-sandbox                      # preview
        st projects delete persona-sandbox --confirm a1b2c3d4   # execute
    """
    run_delete(project_id, confirm=confirm)
