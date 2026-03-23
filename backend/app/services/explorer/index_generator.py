"""Index file generator for Explorer service.

Generates a .index.yaml file at project root with environment info, services,
CLI commands, pages, endpoints, tables, background tasks, and folder structure.
Output is designed to be scannable by AI agents.
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
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


def get_project_urls(project_id: str) -> dict[str, str]:
    """Get derived project URLs from detected ports (preferred) or project config.

    Port-derived localhost URLs take precedence over base_url to avoid stale
    or environment-specific values (e.g. Proxmox IPs, production domains).
    """
    from .base import get_project_config

    project = get_project_config(project_id) or {}
    services = get_services(project_id)

    urls: dict[str, str] = {}

    frontend_port = services.get("frontend_port")
    if frontend_port:
        urls["frontend"] = f"http://localhost:{frontend_port}"
    else:
        base_url = project.get("base_url")
        if isinstance(base_url, str) and base_url:
            urls["frontend"] = base_url.rstrip("/")

    backend_port = services.get("backend_port")
    if backend_port:
        urls["api"] = f"http://localhost:{backend_port}/api"

    return urls


def get_network_info() -> dict[str, str]:
    """Get host network identity for cross-machine URL construction.

    Returns host_ip (first LAN address) and hostname so agents can build
    URLs reachable from remote machines (e.g. sf-browser on a test VM).
    """
    info: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            info["host_ip"] = result.stdout.strip().split()[0]
    except (OSError, subprocess.TimeoutExpired):
        pass
    with contextlib.suppress(OSError):
        info["hostname"] = socket.gethostname()
    return info


def get_explorer_summary(project_id: str) -> dict[str, Any]:
    """Get the highest-signal Explorer trust metadata for `.index.yaml`."""
    from .scan_ops import get_scan_overview

    overview = get_scan_overview(project_id)
    last_completed = overview.get("last_completed_scan") or {}
    symbol_stats = overview.get("symbol_stats") or {}
    type_summaries = overview.get("type_summaries") or {}

    return {
        "scan_status": overview.get("scan_status", {}).get("status"),
        "last_completed_scan": last_completed.get("completed_at"),
        "last_scan_type": last_completed.get("scan_type"),
        "entry_counts": {
            entry_type: summary.get("total", 0)
            for entry_type, summary in type_summaries.items()
        },
        "symbol_count": symbol_stats.get("count", 0),
        "stale_metadata_count": overview.get("stale_metadata_count", 0),
    }


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
        ("urls", get_project_urls(project_id)),
        ("network", get_network_info()),
        ("cli", get_cli_info(project_id)),
        ("explorer", get_explorer_summary(project_id)),
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
        logger.warning("No root path found for project %s", project_id)
        return None
    index_path = Path(root_path) / ".index.yaml"
    tmp_path = index_path.with_name(f"{index_path.name}.tmp")
    try:
        tmp_path.write_text(generate_index(project_id))
        tmp_path.rename(index_path)
        logger.info("Wrote index file: %s", index_path)
        return str(index_path)
    except OSError as e:
        logger.error("Failed to write index file %s: %s", index_path, e)
        return None


def write_all_index_files() -> dict[str, str | None]:
    """Generate index files for all projects."""
    from ...storage.connection import get_cursor

    results: dict[str, str | None] = {}
    with get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE root_path IS NOT NULL")
        rows = cur.fetchall()
    for (project_id,) in rows:
        try:
            results[project_id] = write_index_file(project_id)
        except Exception as e:
            logger.error("Failed to generate index for %s: %s", project_id, e)
            results[project_id] = None
    return results
