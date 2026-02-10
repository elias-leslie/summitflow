"""Component grouping - Suggest components from files, endpoints, and pages.

Groups related entries into logical components:
- Directory groups: Files in the same directory
- Endpoint groups: Endpoints with common path prefixes
- Page groups: Pages with common route prefixes
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, TypedDict

from ...storage import explorer as explorer_storage


class ComponentSuggestion(TypedDict):
    """A suggested component grouping."""

    suggested_name: str
    type: str
    path: str
    entry_count: int
    entries: list[dict[str, str | None]]


def suggest_components(project_id: str) -> list[ComponentSuggestion]:
    """Suggest components by grouping files by directory and endpoints by prefix.

    Args:
        project_id: Project ID for scoping

    Returns:
        List of suggested components sorted by entry count (descending)
    """
    components: list[ComponentSuggestion] = []

    components.extend(_group_files_by_directory(project_id))
    components.extend(_group_endpoints_by_prefix(project_id))
    components.extend(_group_pages_by_route(project_id))

    return sorted(components, key=lambda c: c["entry_count"], reverse=True)


def _group_files_by_directory(project_id: str) -> list[ComponentSuggestion]:
    """Group files by their top 2 directory levels."""
    files = explorer_storage.get_entries(project_id, {"type": "file", "limit": 10000})

    dir_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for file_entry in files:
        path = file_entry.get("path", "")
        dir_key = _extract_directory_key(path)
        dir_groups[dir_key].append(file_entry)

    components: list[ComponentSuggestion] = []
    skip_dirs = {"node_modules", ".git", "__pycache__", ".next", "dist", "build"}

    for dir_path, entries in dir_groups.items():
        if len(entries) < 3:
            continue
        if any(skip in dir_path for skip in skip_dirs):
            continue

        components.append({
            "suggested_name": _path_to_component_name(dir_path),
            "type": "directory",
            "path": dir_path,
            "entry_count": len(entries),
            "entries": [{"id": e.get("id"), "path": e.get("path")} for e in entries[:10]],
        })

    return components


def _group_endpoints_by_prefix(project_id: str) -> list[ComponentSuggestion]:
    """Group endpoints by their path prefix."""
    endpoints = explorer_storage.get_entries(project_id, {"type": "endpoint", "limit": 10000})

    endpoint_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for endpoint in endpoints:
        path = endpoint.get("path", "")
        prefix = extract_endpoint_prefix(path)
        if prefix:
            endpoint_groups[prefix].append(endpoint)

    components: list[ComponentSuggestion] = []
    for prefix, entries in endpoint_groups.items():
        if len(entries) < 2:
            continue

        components.append({
            "suggested_name": f"{prefix.replace('/', '-').title()}API",
            "type": "endpoint_group",
            "path": prefix,
            "entry_count": len(entries),
            "entries": [{"id": e.get("id"), "path": e.get("path")} for e in entries[:10]],
        })

    return components


def _group_pages_by_route(project_id: str) -> list[ComponentSuggestion]:
    """Group pages by their route prefix."""
    pages = explorer_storage.get_entries(project_id, {"type": "page", "limit": 10000})

    page_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in pages:
        path = page.get("path", "")
        parts = path.strip("/").split("/")
        if len(parts) >= 1 and parts[0]:
            page_groups[parts[0]].append(page)

    components: list[ComponentSuggestion] = []
    for prefix, entries in page_groups.items():
        if len(entries) < 2:
            continue

        components.append({
            "suggested_name": f"{prefix.title()}Pages",
            "type": "page_group",
            "path": prefix,
            "entry_count": len(entries),
            "entries": [{"id": e.get("id"), "path": e.get("path")} for e in entries[:10]],
        })

    return components


def _extract_directory_key(path: str) -> str:
    """Extract top 2 directory levels from a file path."""
    parts = path.split("/")
    if len(parts) >= 2:
        return "/".join(parts[:2])
    if len(parts) == 1:
        return parts[0]
    return "root"


def _path_to_component_name(path: str) -> str:
    """Convert a directory path to a component name."""
    parts = path.strip("/").split("/")
    meaningful = [p for p in parts if p and p not in {"app", "src", "lib"}]

    name_parts = meaningful[-2:] if meaningful else parts[-2:]
    return "".join(p.title().replace("_", "").replace("-", "") for p in name_parts)


def extract_endpoint_prefix(path: str) -> str:
    """Extract the prefix from an endpoint path.

    Args:
        path: Endpoint path (may include HTTP method prefix)

    Returns:
        First meaningful path segment (e.g., "users" from "/api/v1/users/{id}")
    """
    # Remove HTTP method if present
    parts = path.split()
    if len(parts) > 1:
        path = parts[-1]

    # Extract meaningful path segment
    path_parts = path.strip("/").split("/")
    skip = {"api", "v1", "v2", "projects", "{project_id}"}
    meaningful = [p for p in path_parts if p and p not in skip and not p.startswith("{")]

    return meaningful[0] if meaningful else ""
