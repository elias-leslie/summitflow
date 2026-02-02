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

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ...logging_config import get_logger
from ...storage import explorer as storage
from .base import get_project_root
from .environment import get_cli_info, get_environment
from .port_detection import get_services

logger = get_logger(__name__)



def get_pages(project_id: str) -> list[str]:
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


def get_endpoints(project_id: str) -> list[str]:
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


def get_tables(project_id: str) -> list[str]:
    """Get all database tables."""
    entries = storage.get_entries(project_id, {"type": "table", "limit": 100})
    return sorted([e.get("name", e.get("path", "")) for e in entries])


def get_background_tasks(project_id: str) -> list[str]:
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


def get_folders(project_id: str) -> dict[str, str]:
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
    environment = get_environment(project_id)
    services = get_services(project_id)
    cli = get_cli_info(project_id)
    pages = get_pages(project_id)
    endpoints = get_endpoints(project_id)
    tables = get_tables(project_id)
    tasks = get_background_tasks(project_id)
    folders = get_folders(project_id)

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
