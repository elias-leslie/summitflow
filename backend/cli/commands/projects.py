"""Project management commands for the CLI."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

from ..config import get_config
from ..output import output_error, output_json

logger = logging.getLogger(__name__)

app = typer.Typer(help="Project management commands")


def _get_projects(api_base: str) -> list[dict[str, Any]]:
    """Fetch all projects from API."""
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{api_base}/projects")
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list):
                    return result
    except (httpx.HTTPError, OSError):
        logger.debug("Failed to fetch projects from API")
    return []


def _detect_current_project(api_base: str) -> str | None:
    """Detect project from current working directory."""
    cwd = Path.cwd().resolve()
    projects = _get_projects(api_base)

    for project in projects:
        root_path = project.get("root_path")
        if not root_path:
            continue

        root = Path(root_path).resolve()
        try:
            cwd.relative_to(root)
            return project.get("id")
        except ValueError:
            continue

    return None


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
    api_base = os.getenv("ST_API_BASE", "http://localhost:8001/api")
    projects = _get_projects(api_base)

    if not projects:
        output_error("No projects found or API unavailable")
        raise typer.Exit(1)

    # Detect current project from cwd
    current_project = _detect_current_project(api_base)

    # Add current marker
    for project in projects:
        project["current"] = project.get("id") == current_project

    if verbose:
        output_json(projects)
    else:
        # Simplified output
        simplified = [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "root_path": p.get("root_path"),
                "current": p.get("current", False),
            }
            for p in projects
        ]
        output_json(simplified)


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
                    "ST_PROJECT_ID" if os.getenv("ST_PROJECT_ID") else "auto-detected from cwd"
                ),
            }
        )
    except SystemExit:
        # get_config exits if no project found - that error message is sufficient
        raise
