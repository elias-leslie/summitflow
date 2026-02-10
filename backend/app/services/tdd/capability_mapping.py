"""Capability mapping - Convert endpoints and pages to capability suggestions.

Maps explorer entries to suggested capability names and descriptions.
"""

from __future__ import annotations

from typing import Any, TypedDict


class CapabilitySuggestion(TypedDict):
    """A suggested capability derived from an entry."""

    suggested_name: str
    source: str
    source_path: str
    description: str


def suggest_capabilities(component_entries: list[dict[str, Any]]) -> list[CapabilitySuggestion]:
    """Suggest capabilities for a set of component entries.

    Args:
        component_entries: List of explorer entries in a component

    Returns:
        List of suggested capability names and descriptions
    """
    capabilities: list[CapabilitySuggestion] = []

    for entry in component_entries:
        path = entry.get("path", "")
        entry_type = entry.get("entry_type", "")

        if entry_type == "endpoint":
            capability = _endpoint_to_capability(entry)
            if capability:
                capabilities.append(capability)
        elif entry_type == "page":
            capability = _page_to_capability(path)
            if capability:
                capabilities.append(capability)

    return capabilities


def _endpoint_to_capability(entry: dict[str, Any]) -> CapabilitySuggestion | None:
    """Convert an endpoint entry to a capability suggestion."""
    path = entry.get("path", "")
    method = entry.get("metadata", {}).get("method", "GET")

    cap_name = endpoint_to_capability_name(path, method)
    if not cap_name:
        return None

    return {
        "suggested_name": cap_name,
        "source": "endpoint",
        "source_path": path,
        "description": f"{method} {path} should work correctly",
    }


def _page_to_capability(path: str) -> CapabilitySuggestion | None:
    """Convert a page path to a capability suggestion."""
    cap_name = page_to_capability_name(path)
    if not cap_name:
        return None

    return {
        "suggested_name": cap_name,
        "source": "page",
        "source_path": path,
        "description": f"Page at {path} should render correctly",
    }


def endpoint_to_capability_name(path: str, method: str) -> str:
    """Convert an endpoint to a capability name.

    Args:
        path: Endpoint path
        method: HTTP method (GET, POST, PUT, PATCH, DELETE)

    Returns:
        Capability name like "create_users" or "view_tasks"
    """
    from .component_grouping import extract_endpoint_prefix

    prefix = extract_endpoint_prefix(path)
    if not prefix:
        return ""

    action_map = {
        "GET": "view",
        "POST": "create",
        "PUT": "update",
        "PATCH": "update",
        "DELETE": "delete",
    }
    action = action_map.get(method, "handle")
    return f"{action}_{prefix}"


def page_to_capability_name(path: str) -> str:
    """Convert a page path to a capability name.

    Args:
        path: Page route path

    Returns:
        Capability name like "view_dashboard"
    """
    parts = path.strip("/").split("/")
    meaningful = [p for p in parts if p and not p.startswith("[")]

    return f"view_{meaningful[-1]}" if meaningful else ""
