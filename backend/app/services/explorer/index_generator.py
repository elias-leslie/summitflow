"""Index file generator for Explorer service.

Generates a .index.yaml file at project root containing:
- Health summary (healthy/warning/error counts)
- Hotspots (top refactor targets)
- Pages (all frontend routes)
- Endpoints (grouped by category)
- Tables (all database tables)
- Background tasks (all scheduled jobs)
- Dependencies summary
- Folder structure

Constraint: Output should be <150 lines to stay scannable by AI.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ...logging_config import get_logger
from ...storage import explorer as storage
from .base import get_project_root

logger = get_logger(__name__)


def _get_health_summary(project_id: str) -> dict[str, int]:
    """Get health status counts."""
    stats = storage.get_stats(project_id)
    by_health: dict[str, int] = stats.get("by_health", {})
    return by_health


def _get_hotspots(project_id: str, limit: int = 5) -> list[str]:
    """Get top refactor targets as compact strings."""
    targets = storage.get_refactor_targets(project_id, limit=limit, code_only=True)

    hotspots = []
    for t in targets.get("targets", []):
        parts = [t["path"]]
        details = []

        if t.get("lines_of_code", 0) > 500:
            details.append(f"{t['lines_of_code']} LOC")
        if t.get("complexity_score", 0) > 20:
            details.append(f"complexity: {t['complexity_score']:.0f}")
        if not t.get("test_file_exists", True):
            details.append("untested")

        if details:
            parts.append(f"({', '.join(details)})")

        hotspots.append(" ".join(parts))

    return hotspots


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


def _get_endpoints_grouped(project_id: str) -> dict[str, int]:
    """Get endpoints grouped by category."""
    entries = storage.get_entries(project_id, {"type": "endpoint", "limit": 200})

    categories: dict[str, int] = defaultdict(int)
    for e in entries:
        category = e.get("metadata", {}).get("category", "other")
        categories[category] += 1

    # Sort by count descending
    return dict(sorted(categories.items(), key=lambda x: -x[1]))


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


def _get_dependencies_summary(project_id: str) -> dict[str, Any]:
    """Get dependencies summary."""
    entries = storage.get_entries(project_id, {"type": "dependency", "limit": 500})

    total = len(entries)
    outdated = 0
    vulnerable = 0

    for e in entries:
        meta = e.get("metadata", {})
        if meta.get("is_outdated"):
            outdated += 1
        vulns = meta.get("vulnerabilities", {})
        if vulns and (vulns.get("critical", 0) + vulns.get("high", 0) > 0):
            vulnerable += 1

    return {"total": total, "outdated": outdated, "vulnerable": vulnerable}


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
    health = _get_health_summary(project_id)
    hotspots = _get_hotspots(project_id)
    pages = _get_pages(project_id)
    endpoints = _get_endpoints_grouped(project_id)
    tables = _get_tables(project_id)
    tasks = _get_background_tasks(project_id)
    deps = _get_dependencies_summary(project_id)
    folders = _get_folders(project_id)

    # Build index structure
    index_data: dict[str, Any] = {
        "project": project_id,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }

    # Health summary
    if health:
        index_data["health"] = health

    # Hotspots (actionable)
    if hotspots:
        index_data["hotspots"] = hotspots

    # Pages (what the app does)
    if pages:
        index_data["pages"] = pages

    # Endpoints (API surface, grouped)
    if endpoints:
        index_data["endpoints"] = endpoints

    # Tables (data model)
    if tables:
        index_data["tables"] = tables

    # Background tasks
    if tasks:
        index_data["tasks"] = tasks

    # Dependencies summary
    if deps["total"] > 0:
        index_data["dependencies"] = deps

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
