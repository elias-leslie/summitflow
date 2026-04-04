"""Helper functions and constants for the projects CLI command."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
import typer

from app.config import DEFAULT_API_BASE

from ..output import output_error, output_json, output_success
from ._http_errors import parse_error_detail

logger = logging.getLogger(__name__)

# Constants
ENV_API_BASE = "ST_API_BASE"
ENV_PROJECT_ID = "ST_PROJECT_ID"
DEFAULT_HEALTH_ENDPOINT = "/health"
NO_PROJECTS_MSG = "No projects found or API unavailable"
UNEXPECTED_RESPONSE_MSG = "Unexpected API response"
CREATE_FIELDS_MSG = (
    "Provide --base-url or use --summitflow-hosted with backend-hosted defaults configured"
)
UPDATE_FIELDS_MSG = (
    "At least one field must be provided "
    "(--name, --base-url, --root-path, --health-endpoint)"
)


def _build_onboarding_payload(
    *,
    backup_frequency: str,
    backup_retention_days: int,
    queue_initial_backup: bool,
) -> dict[str, Any]:
    """Build the standard project onboarding payload."""
    return {
        "enable_backup_schedule": True,
        "backup_frequency": backup_frequency,
        "backup_retention_days": backup_retention_days,
        "queue_initial_backup": queue_initial_backup,
    }


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
                detail = parse_error_detail(response)
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
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return None
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


def run_root(project_id: str) -> None:
    """Implementation for `projects root`."""
    project = projects_api("GET", f"/{project_id}")
    if not isinstance(project, dict):
        output_error(UNEXPECTED_RESPONSE_MSG)
        raise typer.Exit(1)

    root_path = project.get("root_path")
    if not root_path:
        output_error(f"Project '{project_id}' has no root_path configured")
        raise typer.Exit(1)

    typer.echo(root_path)


def run_create(
    project_id: str,
    name: str,
    base_url: str | None,
    root_path: str | None,
    health_endpoint: str,
    summitflow_hosted: bool = False,
    permission_tier: str | None = None,
    auto_exec_enabled: bool | None = None,
    execution_start_hour: int | None = None,
    execution_end_hour: int | None = None,
    onboarding: bool = False,
    backup_frequency: str = "daily",
    backup_retention_days: int = 30,
    queue_initial_backup: bool = True,
) -> None:
    """Implementation for `projects create`."""
    effective_root_path = root_path
    if summitflow_hosted:
        effective_root_path = effective_root_path or f"/srv/workspaces/projects/{project_id}"
    if not base_url and not summitflow_hosted:
        output_error(CREATE_FIELDS_MSG)
        raise typer.Exit(1)
    body: dict[str, Any] = {
        "id": project_id,
        "name": name,
        "health_endpoint": health_endpoint,
    }
    if base_url is not None:
        body["base_url"] = base_url
    if effective_root_path is not None:
        body["root_path"] = effective_root_path
    if summitflow_hosted:
        body["summitflow_hosted"] = True
    permission_payload = {
        "permission_tier": permission_tier,
        "auto_exec_enabled": auto_exec_enabled,
        "execution_start_hour": execution_start_hour,
        "execution_end_hour": execution_end_hour,
    }
    normalized_permission_payload = {
        key: value for key, value in permission_payload.items() if value is not None
    }
    if normalized_permission_payload:
        body["agent_hub_permission"] = normalized_permission_payload
    if onboarding:
        body["onboarding"] = _build_onboarding_payload(
            backup_frequency=backup_frequency,
            backup_retention_days=backup_retention_days,
            queue_initial_backup=queue_initial_backup,
        )
    result = projects_api("POST", json=body)
    output_success(f"Created project '{project_id}'")
    if onboarding:
        output_success(f"Queued onboarding for '{project_id}'")
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


def run_onboard(
    project_id: str,
    *,
    backup_frequency: str = "daily",
    backup_retention_days: int = 30,
    queue_initial_backup: bool = True,
) -> None:
    """Implementation for `projects onboard`."""
    payload = _build_onboarding_payload(
        backup_frequency=backup_frequency,
        backup_retention_days=backup_retention_days,
        queue_initial_backup=queue_initial_backup,
    )
    result = projects_api("POST", f"/{project_id}/onboard", json=payload)
    output_success(f"Queued onboarding for project '{project_id}'")
    output_json(result)


def run_delete(project_id: str, *, confirm: str | None = None) -> None:
    """Implementation for `projects delete` — two-pass confirmation."""
    from ..lib.confirm_token import confirm_gate

    command_key = f"projects-delete-{project_id}"

    preview_lines: list[str] = []
    if confirm is None:
        project = projects_api("GET", f"/{project_id}")
        name = project.get("name", project_id) if isinstance(project, dict) else project_id
        preview_lines = [
            f"DELETE PROJECT: {project_id}",
            f"  Name: {name}",
            "",
            "This will permanently delete the project record from the database.",
            "Tasks, sessions, and other data linked to this project may be affected.",
        ]

    confirm_gate(command_key, confirm, preview_lines, f"st projects delete {project_id}")

    projects_api("DELETE", f"/{project_id}")
    output_success(f"Deleted project '{project_id}'")
