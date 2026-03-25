"""Port detection utilities for Explorer service."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from psycopg import sql

from ...logging_config import get_logger

logger = get_logger(__name__)

# Shared infrastructure ports (standard, rarely change)
INFRASTRUCTURE_PORTS = {
    "postgres": 5432,
    "redis": 6379,
}


def extract_port_from_service_content(content: str) -> int | None:
    """Extract port from systemd service file content."""
    port_match = re.search(r"--port\s+(\d+)", content)
    if port_match:
        return int(port_match.group(1))

    env_match = re.search(r"PORT=(\d+)", content)
    if env_match:
        return int(env_match.group(1))

    return None


def _read_service_port(service_file: Path) -> int | None:
    """Read and extract port from a single service file, ignoring OSError."""
    try:
        return extract_port_from_service_content(service_file.read_text())
    except OSError:
        return None


def get_port_from_systemd(project_id: str, service_type: str) -> int | None:
    """Extract port from systemd user service file.

    Searches ~/.config/systemd/user/ using:
    1. Direct name: {project_id}-{service_type}.service
    2. WorkingDirectory containing /{project_id}/{service_type}
    """
    systemd_dir = Path.home() / ".config/systemd/user"
    if not systemd_dir.exists():
        return None

    direct_match = systemd_dir / f"{project_id}-{service_type}.service"
    if direct_match.exists():
        port = _read_service_port(direct_match)
        if port:
            return port

    workdir_pattern = f"/{project_id}/{service_type}"
    for service_file in systemd_dir.glob(f"*-{service_type}.service"):
        try:
            content = service_file.read_text()
        except OSError:
            continue
        if workdir_pattern in content:
            port = extract_port_from_service_content(content)
            if port:
                return port

    return None


def sync_ports_to_db(project_id: str, backend_port: int | None, frontend_port: int | None) -> None:
    """Sync detected ports to projects table."""
    from ...storage.connection import get_connection

    updates: list[sql.Composed] = []
    params: list[int | str] = []

    if backend_port is not None:
        updates.append(sql.SQL("backend_port = {}").format(sql.Placeholder()))
        params.append(backend_port)
    if frontend_port is not None:
        updates.append(sql.SQL("frontend_port = {}").format(sql.Placeholder()))
        params.append(frontend_port)

    if not updates:
        return

    params.append(project_id)

    with get_connection() as conn, conn.cursor() as cur:
        query = sql.SQL("UPDATE projects SET {updates} WHERE id = %s").format(
            updates=sql.SQL(", ").join(updates)
        )
        cur.execute(query, params)
        conn.commit()

    logger.debug(
        "Synced ports to DB for %s: backend=%s, frontend=%s",
        project_id, backend_port, frontend_port,
    )


def _ports_needing_sync(
    systemd_val: int | None,
    db_val: int | None,
) -> int | None:
    """Return systemd_val if it differs from db_val, otherwise None."""
    return systemd_val if systemd_val and systemd_val != db_val else None


def get_services(project_id: str) -> dict[str, Any]:
    """Get service and infrastructure port information.

    Port resolution order:
    1. Detect from systemd user services (source of truth)
    2. Auto-sync to projects table if different
    3. Fall back to DB values if systemd detection fails
    """
    from .base import get_project_config

    systemd_backend = get_port_from_systemd(project_id, "backend")
    systemd_frontend = get_port_from_systemd(project_id, "frontend")

    project = get_project_config(project_id)
    db_backend = project.get("backend_port") if project else None
    db_frontend = project.get("frontend_port") if project else None

    backend_port = systemd_backend or db_backend
    frontend_port = systemd_frontend or db_frontend

    sync_backend = _ports_needing_sync(systemd_backend, db_backend)
    sync_frontend = _ports_needing_sync(systemd_frontend, db_frontend)
    if sync_backend or sync_frontend:
        sync_ports_to_db(project_id, sync_backend, sync_frontend)

    services: dict[str, Any] = {}
    if backend_port:
        services["backend_port"] = backend_port
    if frontend_port:
        services["frontend_port"] = frontend_port
    services["infrastructure"] = INFRASTRUCTURE_PORTS.copy()

    return services
