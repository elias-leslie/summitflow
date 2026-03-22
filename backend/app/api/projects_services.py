"""Project services configuration endpoint.

Provides the GET /api/projects/{id}/services endpoint for retrieving
dynamic service configuration from .st/services.yaml.
"""

from __future__ import annotations

from fastapi import HTTPException

from cli.lib.project_config import (
    get_services_config_path,
    load_services_config,
)

from ..schemas.project import ProjectServicesResponse, ServiceConfigSchema
from ..storage.connection import get_cursor


def _get_project_root_path(project_id: str) -> str | None:
    """Get the root_path for a project from the database.

    Args:
        project_id: Project identifier.

    Returns:
        Root path string or None if not set.

    Raises:
        HTTPException: If project not found.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT root_path FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    root_path: str | None = row[0]
    return root_path


def get_project_services(project_id: str) -> ProjectServicesResponse:
    """Get service configuration for a project.

    Loads configuration from .st/services.yaml if available,
    otherwise returns default configuration.

    Args:
        project_id: Project identifier.

    Returns:
        ProjectServicesResponse with services configuration.

    Raises:
        HTTPException: If project not found or root_path not configured.
    """
    root_path = _get_project_root_path(project_id)

    if not root_path:
        raise HTTPException(
            status_code=400,
            detail=f"Project {project_id} does not have a root_path configured",
        )

    # Load configuration
    config = load_services_config(root_path)

    # Determine source
    config_path = get_services_config_path(root_path)
    config_source = "file" if config_path.exists() else "default"

    # Convert to response schema
    services_dict = {
        name: ServiceConfigSchema(
            name=svc.name,
            command=svc.command,
            port=svc.port,
            worktree_port_base=svc.worktree_port_base,
            worktree_port_range=svc.worktree_port_range,
            cwd=svc.cwd,
            env_file=svc.env_file,
            build_command=svc.build_command,
        )
        for name, svc in config.services.items()
    }

    return ProjectServicesResponse(
        project_id=project_id,
        services=services_dict,
        config_source=config_source,
    )
