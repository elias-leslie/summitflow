"""Index file generator for Explorer service.

Generates a .index.yaml file at project root containing:
- Environment info (Python/Node versions, package manager)
- Services and ports
- CLI commands
- Pages (all frontend routes)
- Endpoints (all API routes, fully expanded)
- Tables (all database tables)
- Background tasks (all scheduled jobs)
- Folder structure

Constraint: Output should be scannable by AI agents.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ...logging_config import get_logger
from ...storage import explorer as storage
from .base import get_project_root

logger = get_logger(__name__)


# Shared infrastructure ports (standard, rarely change)
INFRASTRUCTURE_PORTS = {
    "neo4j": 7687,
    "postgres": 5432,
    "redis": 6379,
}


def _extract_port_from_service_content(content: str) -> int | None:
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


def _get_port_from_systemd(project_id: str, service_type: str) -> int | None:
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
            port = _extract_port_from_service_content(content)
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
                port = _extract_port_from_service_content(content)
                if port:
                    return port
        except OSError:
            continue

    return None


def _get_environment(project_id: str) -> dict[str, Any]:
    """Get environment info from pyproject.toml and package.json.

    Scans for Python version (requires-python) and Node version (engines.node).
    """
    root_path = get_project_root(project_id)
    if not root_path:
        return {}

    root = Path(root_path)
    env_info: dict[str, Any] = {}

    # Check for Python project (pyproject.toml in root or backend/)
    pyproject_paths = [root / "pyproject.toml", root / "backend" / "pyproject.toml"]
    for pyproject_path in pyproject_paths:
        if pyproject_path.exists():
            try:
                content = pyproject_path.read_text()
                # Parse requires-python
                match = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    env_info["python_version"] = match.group(1)
                # Check for venv
                venv_path = pyproject_path.parent / ".venv"
                if venv_path.exists():
                    env_info["venv_path"] = str(venv_path.relative_to(root))
                break
            except OSError:
                pass

    # Check for Node project (package.json in root or frontend/)
    package_paths = [root / "package.json", root / "frontend" / "package.json"]
    for package_path in package_paths:
        if package_path.exists():
            try:
                content = json.loads(package_path.read_text())
                # Check engines.node
                if "engines" in content and "node" in content["engines"]:
                    env_info["node_version"] = content["engines"]["node"]
                # Detect package manager
                if (root / "pnpm-lock.yaml").exists():
                    env_info["package_manager"] = "pnpm"
                elif (root / "yarn.lock").exists():
                    env_info["package_manager"] = "yarn"
                elif (root / "package-lock.json").exists() or package_path.exists():
                    env_info["package_manager"] = "npm"
                break
            except (OSError, json.JSONDecodeError):
                pass

    return env_info


def _sync_ports_to_db(project_id: str, backend_port: int | None, frontend_port: int | None) -> None:
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


def _get_services(project_id: str) -> dict[str, Any]:
    """Get service and infrastructure port information.

    Port resolution (fully automatic):
    1. Detect from systemd user services (source of truth)
    2. Auto-sync to projects table if different
    3. Fall back to DB values only if systemd detection fails
    """
    from .base import get_project_config

    services: dict[str, Any] = {}

    # Primary: auto-detect from systemd (reads actual configuration)
    systemd_backend = _get_port_from_systemd(project_id, "backend")
    systemd_frontend = _get_port_from_systemd(project_id, "frontend")

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
        _sync_ports_to_db(project_id, sync_backend, sync_frontend)

    if backend_port:
        services["backend_port"] = backend_port
    if frontend_port:
        services["frontend_port"] = frontend_port

    # Add infrastructure ports (shared across all projects)
    services["infrastructure"] = INFRASTRUCTURE_PORTS.copy()

    return services


def _get_cli_info(project_id: str) -> dict[str, Any]:
    """Get CLI command information from pyproject.toml.

    Parses [project.scripts] to find CLI entry points.
    """
    root_path = get_project_root(project_id)
    if not root_path:
        return {}

    root = Path(root_path)
    cli_info: dict[str, Any] = {}

    # Check pyproject.toml for CLI scripts
    pyproject_paths = [root / "pyproject.toml", root / "backend" / "pyproject.toml"]
    for pyproject_path in pyproject_paths:
        if pyproject_path.exists():
            try:
                content = pyproject_path.read_text()
                # Find [project.scripts] section
                # Pattern: key = "module:func"
                scripts_match = re.search(
                    r"\[project\.scripts\](.*?)(?:\n\[|\Z)", content, re.DOTALL
                )
                if scripts_match:
                    scripts_section = scripts_match.group(1)
                    # Parse each script entry
                    for line in scripts_section.strip().split("\n"):
                        if "=" in line and not line.strip().startswith("#"):
                            parts = line.split("=", 1)
                            cmd_name = parts[0].strip()
                            if cmd_name:
                                cli_info["primary_command"] = cmd_name
                                cli_info["help_command"] = f"{cmd_name} --help"
                                break
                break
            except OSError:
                pass

    # Add common commands for known projects
    if project_id == "summitflow":
        cli_info["common_commands"] = [
            "st work <task-id>  # Set active task context",
            "st context         # Show current task details",
            "st step pass <subtask> <N>  # Mark step as passed",
            "st subtask pass    # Mark subtask as passed",
            "st close           # Close completed task",
        ]
    elif project_id == "agent-hub":
        cli_info["common_commands"] = [
            "st complete --agent <slug> <prompt>  # Route to agent",
            "st memory save <content>  # Save learning to memory",
            "st memory search <query>  # Semantic search",
        ]

    return cli_info


def _get_pages(project_id: str) -> list[str]:
    """Get all frontend pages."""
    entries = storage.get_entries(project_id, {"type": "page", "limit": 100})

    pages = []
    for e in entries:
        path = e.get("path", "")
        name = e.get("name", "")
        if name and name != path:
            pages.append(f"{path} ({name})")
        else:
            pages.append(path)

    return sorted(pages)


def _get_endpoints(project_id: str) -> list[str]:
    """Get all API endpoints, fully expanded."""
    entries = storage.get_entries(project_id, {"type": "endpoint", "limit": 500})

    endpoints = []
    for e in entries:
        path = e.get("path", "")
        meta = e.get("metadata", {})
        func_name = meta.get("function_name", "")

        # Format: "GET /api/tasks/{id} (get_task)"
        if func_name:
            endpoints.append(f"{path} ({func_name})")
        else:
            endpoints.append(path)

    return sorted(endpoints)


def _get_tables(project_id: str) -> list[str]:
    """Get all database tables."""
    entries = storage.get_entries(project_id, {"type": "table", "limit": 100})
    return sorted([e.get("name", e.get("path", "")) for e in entries])


def _get_background_tasks(project_id: str) -> list[str]:
    """Get all background/scheduled tasks."""
    entries = storage.get_entries(project_id, {"type": "task", "limit": 50})

    tasks = []
    for e in entries:
        name = e.get("name", "")
        schedule = e.get("metadata", {}).get("schedule_human", "")
        if schedule:
            tasks.append(f"{name} ({schedule})")
        else:
            tasks.append(name)

    return sorted(tasks)


def _get_folders(project_id: str) -> dict[str, str]:
    """Get folder structure with file counts and patterns."""
    entries = storage.get_entries(project_id, {"type": "file", "limit": 10000})

    if not entries:
        return {}

    folders: dict[str, dict[str, Any]] = {}

    for entry in entries:
        path = entry.get("path", "")
        parts = path.split("/")
        folder = "(root)" if len(parts) < 2 else parts[0]

        if folder not in folders:
            folders[folder] = {"files": 0, "patterns": set()}

        folders[folder]["files"] += 1

        # Detect patterns
        path_lower = path.lower()
        if "test" in path_lower or "spec" in path_lower:
            folders[folder]["patterns"].add("tests")
        if "api" in path_lower or "route" in path_lower:
            folders[folder]["patterns"].add("api")
        if "component" in path_lower:
            folders[folder]["patterns"].add("components")
        if "service" in path_lower:
            folders[folder]["patterns"].add("services")

    # Format output
    output: dict[str, str] = {}
    for folder, info in sorted(folders.items()):
        patterns = sorted(info["patterns"])
        if patterns:
            output[folder] = f"{info['files']} files - {', '.join(patterns)}"
        else:
            output[folder] = f"{info['files']} files"

    return output


def generate_index(project_id: str) -> str:
    """Generate a YAML index string from explorer data.

    Args:
        project_id: Project to generate index for

    Returns:
        YAML string with comprehensive project overview
    """
    # Gather all data
    environment = _get_environment(project_id)
    services = _get_services(project_id)
    cli = _get_cli_info(project_id)
    pages = _get_pages(project_id)
    endpoints = _get_endpoints(project_id)
    tables = _get_tables(project_id)
    tasks = _get_background_tasks(project_id)
    folders = _get_folders(project_id)

    # Build index structure
    index_data: dict[str, Any] = {
        "project": project_id,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }

    # Environment info (Python/Node versions, etc.)
    if environment:
        index_data["environment"] = environment

    # Services and ports
    if services:
        index_data["services"] = services

    # CLI commands
    if cli:
        index_data["cli"] = cli

    # Pages (frontend routes)
    if pages:
        index_data["pages"] = pages

    # Endpoints (full API surface)
    if endpoints:
        index_data["endpoints"] = endpoints

    # Tables (data model)
    if tables:
        index_data["tables"] = tables

    # Background tasks
    if tasks:
        index_data["tasks"] = tasks

    # Folder structure
    if folders:
        index_data["folders"] = folders

    return yaml.dump(index_data, default_flow_style=False, sort_keys=False)


def write_index_file(project_id: str) -> str | None:
    """Generate and write .index.yaml to project root.

    Args:
        project_id: Project to generate index for

    Returns:
        Path to written file, or None if failed
    """
    root_path = get_project_root(project_id)
    if not root_path:
        logger.warning(f"No root path found for project {project_id}")
        return None

    index_content = generate_index(project_id)
    index_path = Path(root_path) / ".index.yaml"

    try:
        index_path.write_text(index_content)
        logger.info(f"Wrote index file: {index_path}")
        return str(index_path)
    except OSError as e:
        logger.error(f"Failed to write index file {index_path}: {e}")
        return None


def write_all_index_files() -> dict[str, str | None]:
    """Generate index files for all projects.

    Returns:
        Dict mapping project_id to written file path (or None if failed)
    """
    from ...storage.connection import get_connection

    results: dict[str, str | None] = {}

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE root_path IS NOT NULL")
        rows = cur.fetchall()

    for (project_id,) in rows:
        try:
            results[project_id] = write_index_file(project_id)
        except Exception as e:
            logger.error(f"Failed to generate index for {project_id}: {e}")
            results[project_id] = None

    return results
