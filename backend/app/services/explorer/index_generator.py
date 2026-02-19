"""Index file generator for Explorer service.

Generates a .index.yaml file at project root with environment info, services,
CLI commands, pages, endpoints, tables, background tasks, and folder structure.
Output is designed to be scannable by AI agents.
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

_LIMITS = {"page": 100, "endpoint": 500, "table": 100, "task": 50, "file": 10000}
_PATH_PATTERNS = {"tests": ("test", "spec"), "api": ("api", "route"), "components": ("component",), "services": ("service",)}


def get_pages(project_id: str) -> list[str]:
    """Get all frontend pages."""
    entries = storage.get_entries(project_id, {"type": "page", "limit": _LIMITS["page"]})
    result = []
    for e in entries:
        path, name = e.get("path", ""), e.get("name", "")
        result.append(f"{path} ({name})" if name and name != path else path)
    return sorted(result)


def get_endpoints(project_id: str) -> list[str]:
    """Get all API endpoints, fully expanded."""
    entries = storage.get_entries(project_id, {"type": "endpoint", "limit": _LIMITS["endpoint"]})
    result = []
    for e in entries:
        path = e.get("path", "")
        func_name = e.get("metadata", {}).get("function_name", "")
        result.append(f"{path} ({func_name})" if func_name else path)
    return sorted(result)


def get_tables(project_id: str) -> list[str]:
    """Get all database tables."""
    entries = storage.get_entries(project_id, {"type": "table", "limit": _LIMITS["table"]})
    return sorted([e.get("name", e.get("path", "")) for e in entries])


def get_background_tasks(project_id: str) -> list[str]:
    """Get all background/scheduled tasks."""
    entries = storage.get_entries(project_id, {"type": "task", "limit": _LIMITS["task"]})
    result = []
    for e in entries:
        name = e.get("name", "")
        schedule = e.get("metadata", {}).get("schedule_human", "")
        result.append(f"{name} ({schedule})" if schedule else name)
    return sorted(result)


def get_folders(project_id: str) -> dict[str, str]:
    """Get folder structure with file counts and patterns."""
    entries = storage.get_entries(project_id, {"type": "file", "limit": _LIMITS["file"]})
    if not entries:
        return {}

    folders: dict[str, dict[str, Any]] = {}
    for entry in entries:
        path = entry.get("path", "")
        parts = path.split("/")
        folder = "(root)" if len(parts) < 2 else parts[0]
        info = folders.setdefault(folder, {"files": 0, "patterns": set()})
        info["files"] += 1
        path_lower = path.lower()
        info["patterns"].update(
            label for label, kws in _PATH_PATTERNS.items() if any(k in path_lower for k in kws)
        )

    return {
        folder: (
            f"{info['files']} files - {', '.join(sorted(info['patterns']))}"
            if info["patterns"]
            else f"{info['files']} files"
        )
        for folder, info in sorted(folders.items())
    }


def generate_index(project_id: str) -> str:
    """Generate a YAML index string from explorer data."""
    index_data: dict[str, Any] = {
        "project": project_id,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }
    for key, value in [
        ("environment", get_environment(project_id)),
        ("services", get_services(project_id)),
        ("cli", get_cli_info(project_id)),
        ("pages", get_pages(project_id)),
        ("endpoints", get_endpoints(project_id)),
        ("tables", get_tables(project_id)),
        ("tasks", get_background_tasks(project_id)),
        ("folders", get_folders(project_id)),
    ]:
        if value:
            index_data[key] = value
    return yaml.dump(index_data, default_flow_style=False, sort_keys=False)


def write_index_file(project_id: str) -> str | None:
    """Generate and write .index.yaml to project root."""
    root_path = get_project_root(project_id)
    if not root_path:
        logger.warning(f"No root path found for project {project_id}")
        return None
    index_path = Path(root_path) / ".index.yaml"
    try:
        index_path.write_text(generate_index(project_id))
        logger.info(f"Wrote index file: {index_path}")
        return str(index_path)
    except OSError as e:
        logger.error(f"Failed to write index file {index_path}: {e}")
        return None


def write_all_index_files() -> dict[str, str | None]:
    """Generate index files for all projects."""
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
