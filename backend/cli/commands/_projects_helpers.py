"""Helper functions and constants for the projects CLI command."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
import typer

from ..output import output_error, output_json, output_success

logger = logging.getLogger(__name__)

# Constants
DEFAULT_API_BASE = "http://localhost:8001/api"
ENV_API_BASE = "ST_API_BASE"
ENV_PROJECT_ID = "ST_PROJECT_ID"
DEFAULT_HEALTH_ENDPOINT = "/health"
NO_PROJECTS_MSG = "No projects found or API unavailable"
UNEXPECTED_RESPONSE_MSG = "Unexpected API response"
UPDATE_FIELDS_MSG = (
    "At least one field must be provided "
    "(--name, --base-url, --root-path, --health-endpoint)"
)


def get_api_base() -> str:
    """Return the configured API base URL."""
    return os.getenv(ENV_API_BASE, DEFAULT_API_BASE)


def projects_api(
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
    url = f"{get_api_base()}/projects{path}"
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


def detect_current_project() -> str | None:
    """Detect project from current working directory."""
    cwd = Path.cwd().resolve()
    raw = projects_api("GET") or []
    if not isinstance(raw, list):
        return None

    for project in raw:
        root_path = project.get("root_path")
        if not root_path:
            continue
        try:
            cwd.relative_to(Path(root_path).resolve())
            return project.get("id")
        except ValueError:
            continue

    return None


def run_list(*, verbose: bool) -> None:
    """Implementation for `projects list`."""
    projects = projects_api("GET")

    if not projects:
        output_error(NO_PROJECTS_MSG)
        raise typer.Exit(1)

    if not isinstance(projects, list):
        output_error(UNEXPECTED_RESPONSE_MSG)
        raise typer.Exit(1)

    current_id = detect_current_project()
    for p in projects:
        p["current"] = p.get("id") == current_id

    if verbose:
        output_json(projects)
        return

    output_json(
        [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "root_path": p.get("root_path"),
                "current": p.get("current", False),
            }
            for p in projects
        ]
    )


def run_create(
    project_id: str,
    name: str,
    base_url: str,
    root_path: str | None,
    health_endpoint: str,
) -> None:
    """Implementation for `projects create`."""
    body: dict[str, Any] = {
        "id": project_id,
        "name": name,
        "base_url": base_url,
        "health_endpoint": health_endpoint,
    }
    if root_path is not None:
        body["root_path"] = root_path
    result = projects_api("POST", json=body)
    output_success(f"Created project '{project_id}'")
    output_json(result)


def run_update(
    project_id: str,
    name: str | None,
    base_url: str | None,
    root_path: str | None,
    health_endpoint: str | None,
) -> None:
    """Implementation for `projects update`."""
    fields: dict[str, Any] = {
        k: v
        for k, v in {
            "name": name,
            "base_url": base_url,
            "root_path": root_path,
            "health_endpoint": health_endpoint,
        }.items()
        if v is not None
    }
    if not fields:
        output_error(UPDATE_FIELDS_MSG)
        raise typer.Exit(1)
    result = projects_api("PATCH", f"/{project_id}", json=fields)
    output_success(f"Updated project '{project_id}'")
    output_json(result)


def run_delete(project_id: str, *, force: bool) -> None:
    """Implementation for `projects delete`."""
    if not force:
        project = projects_api("GET", f"/{project_id}")
        output_json({"would_delete": project, "hint": "Pass --force to confirm deletion"})
        raise typer.Exit(1)
    projects_api("DELETE", f"/{project_id}")
    output_success(f"Deleted project '{project_id}'")
