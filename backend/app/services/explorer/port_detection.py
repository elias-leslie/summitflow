"""Port detection utilities for Explorer service.

Handles automatic detection of service ports from systemd configuration files
and syncing them to the database.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)


# Shared infrastructure ports (standard, rarely change)
INFRASTRUCTURE_PORTS = {
    "neo4j": 7687,
    "postgres": 5432,
    "redis": 6379,
}


def extract_port_from_service_content(content: str) -> int | None:
    """Extract port from systemd service file content.

    Looks for:
    - --port XXXX in ExecStart line
    - PORT=XXXX in Environment line
    """
    # Try --port XXXX pattern (uvicorn, next.js CLI)
    port_match = re.search(r"--port\s+(\d+)", content)
    if port_match:
        return int(port_match.group(1))

    # Try PORT=XXXX pattern (environment variable)
    env_match = re.search(r"PORT=(\d+)", content)
    if env_match:
        return int(env_match.group(1))

    return None


def get_port_from_systemd(project_id: str, service_type: str) -> int | None:
    """Extract port from systemd user service file.

    Searches ~/.config/systemd/user/ for service files matching:
    1. Direct name: {project_id}-{service_type}.service
    2. WorkingDirectory containing: /{project_id}/{service_type}

    This handles cases where service name differs from project_id
    (e.g., "portfolio" service for "portfolio-ai" project).

    Args:
        project_id: Project name from git root (e.g., "portfolio-ai")
        service_type: "backend" or "frontend"

    Returns:
        Port number or None if not found.
    """
    home = Path.home()
    systemd_dir = home / ".config/systemd/user"

    if not systemd_dir.exists():
        return None

    # Strategy 1: Try direct name match
    direct_match = systemd_dir / f"{project_id}-{service_type}.service"
    if direct_match.exists():
        try:
            content = direct_match.read_text()
            port = extract_port_from_service_content(content)
            if port:
                return port
        except OSError:
            pass

    # Strategy 2: Scan all *-{service_type}.service files for WorkingDirectory match
    # Pattern: WorkingDirectory=%h/{project_id}/{service_type}
    pattern = f"*-{service_type}.service"
    workdir_pattern = f"/{project_id}/{service_type}"

    for service_file in systemd_dir.glob(pattern):
        try:
            content = service_file.read_text()
            if workdir_pattern in content:
                port = extract_port_from_service_content(content)
                if port:
                    return port
        except OSError:
            continue

    return None


def sync_ports_to_db(project_id: str, backend_port: int | None, frontend_port: int | None) -> None:
    """Sync detected ports to projects table.

    Called when systemd detection finds ports that differ from DB.
    This keeps the DB in sync with the actual systemd configuration.
    """
    from ...storage.connection import get_connection

    updates: list[str] = []
    params: list[int | str] = []

    if backend_port is not None:
        updates.append("backend_port = %s")
        params.append(backend_port)
    if frontend_port is not None:
        updates.append("frontend_port = %s")
        params.append(frontend_port)

    if not updates:
        return

    params.append(project_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE projects SET {', '.join(updates)} WHERE id = %s",
            params,
        )
        conn.commit()

    logger.debug(
        f"Synced ports to DB for {project_id}: backend={backend_port}, frontend={frontend_port}"
    )


def get_services(project_id: str) -> dict[str, Any]:
    """Get service and infrastructure port information.

    Port resolution (fully automatic):
    1. Detect from systemd user services (source of truth)
    2. Auto-sync to projects table if different
    3. Fall back to DB values only if systemd detection fails
    """
    from .base import get_project_config

    services: dict[str, Any] = {}

    # Primary: auto-detect from systemd (reads actual configuration)
    systemd_backend = get_port_from_systemd(project_id, "backend")
    systemd_frontend = get_port_from_systemd(project_id, "frontend")

    # Secondary: get current DB values
    project = get_project_config(project_id)
    db_backend = project.get("backend_port") if project else None
    db_frontend = project.get("frontend_port") if project else None

    # Use systemd if detected, otherwise fall back to DB
    backend_port = systemd_backend or db_backend
    frontend_port = systemd_frontend or db_frontend

    # Auto-sync to DB if systemd detected different values
    needs_sync = False
    sync_backend = None
    sync_frontend = None

    if systemd_backend and systemd_backend != db_backend:
        sync_backend = systemd_backend
        needs_sync = True
    if systemd_frontend and systemd_frontend != db_frontend:
        sync_frontend = systemd_frontend
        needs_sync = True

    if needs_sync:
        sync_ports_to_db(project_id, sync_backend, sync_frontend)

    if backend_port:
        services["backend_port"] = backend_port
    if frontend_port:
        services["frontend_port"] = frontend_port

    # Add infrastructure ports (shared across all projects)
    services["infrastructure"] = INFRASTRUCTURE_PORTS.copy()

    return services
