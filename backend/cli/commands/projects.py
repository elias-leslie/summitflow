"""Project management commands for the CLI."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

from ..config import get_config
from ..output import output_error, output_json, output_success

logger = logging.getLogger(__name__)

app = typer.Typer(help="Project management commands")


def _projects_api(
    method: str,
    path: str = "",
    **kwargs: Any,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Call the projects API and return parsed JSON.

    Args:
        method: HTTP method (GET, POST, PATCH, DELETE).
        path: Path appended to /api/projects (e.g. "/{id}").
        **kwargs: Passed to httpx.Client.request (json, params, etc.).

    Returns:
        Parsed JSON response, or None for 204 No Content.

    Raises:
        typer.Exit: On any HTTP or connection error.
    """
    api_base = os.getenv("ST_API_BASE", "http://localhost:8001/api")
    url = f"{api_base}/projects{path}"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.request(method, url, **kwargs)
            if response.status_code == 204:
                return None
            if response.status_code >= 400:
                try:
                    detail = response.json().get("detail", response.text)
                except Exception:
                    detail = response.text
                output_error(f"{response.status_code}: {detail}")
                raise typer.Exit(1)
            return response.json()
    except httpx.HTTPError as e:
        output_error(f"API request failed: {e}")
        raise typer.Exit(1) from None
    except typer.Exit:
        raise
    except OSError as e:
        output_error(f"Connection error: {e}")
        raise typer.Exit(1) from None


def _detect_current_project(api_base: str) -> str | None:
    """Detect project from current working directory."""
    cwd = Path.cwd().resolve()
    projects = _projects_api("GET") or []
    if not isinstance(projects, list):
        return None

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
    projects = _projects_api("GET")

    if not projects:
        output_error("No projects found or API unavailable")
        raise typer.Exit(1)

    if not isinstance(projects, list):
        output_error("Unexpected API response")
        raise typer.Exit(1)

    current_project = _detect_current_project(api_base)

    for project in projects:
        project["current"] = project.get("id") == current_project

    if verbose:
        output_json(projects)
    else:
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
    result = _projects_api("GET", f"/{project_id}")
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
    ] = "/health",
) -> None:
    """Create a new project.

    Examples:
        st projects create persona-sandbox "Persona Sandbox" --base-url http://localhost:3003
        st projects create my-app "My App" -u http://localhost:8080 -r /home/user/my-app
    """
    body: dict[str, Any] = {
        "id": project_id,
        "name": name,
        "base_url": base_url,
        "health_endpoint": health_endpoint,
    }
    if root_path is not None:
        body["root_path"] = root_path

    result = _projects_api("POST", json=body)
    output_success(f"Created project '{project_id}'")
    output_json(result)


@app.command("update")
def update_project(
    project_id: Annotated[str, typer.Argument(help="Project ID to update")],
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="New display name"),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", "-u", help="New base URL"),
    ] = None,
    root_path: Annotated[
        str | None,
        typer.Option("--root-path", "-r", help="New filesystem root path"),
    ] = None,
    health_endpoint: Annotated[
        str | None,
        typer.Option("--health-endpoint", help="New health check endpoint"),
    ] = None,
) -> None:
    """Update an existing project.

    At least one field must be provided.

    Examples:
        st projects update persona-sandbox --name "Persona Sandbox v2"
        st projects update my-app --base-url http://localhost:9090 --root-path /new/path
    """
    fields: dict[str, Any] = {}
    if name is not None:
        fields["name"] = name
    if base_url is not None:
        fields["base_url"] = base_url
    if root_path is not None:
        fields["root_path"] = root_path
    if health_endpoint is not None:
        fields["health_endpoint"] = health_endpoint

    if not fields:
        output_error("At least one field must be provided (--name, --base-url, --root-path, --health-endpoint)")
        raise typer.Exit(1)

    result = _projects_api("PATCH", f"/{project_id}", json=fields)
    output_success(f"Updated project '{project_id}'")
    output_json(result)


@app.command("delete")
def delete_project(
    project_id: Annotated[str, typer.Argument(help="Project ID to delete")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Required to confirm deletion"),
    ] = False,
) -> None:
    """Delete a project.

    Requires --force flag to confirm deletion.

    Examples:
        st projects delete persona-sandbox         # shows what would be deleted
        st projects delete persona-sandbox --force  # actually deletes
    """
    if not force:
        project = _projects_api("GET", f"/{project_id}")
        output_json({"would_delete": project, "hint": "Pass --force to confirm deletion"})
        raise typer.Exit(1)

    _projects_api("DELETE", f"/{project_id}")
    output_success(f"Deleted project '{project_id}'")
