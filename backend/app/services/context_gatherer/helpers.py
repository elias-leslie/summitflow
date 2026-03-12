"""Helper utilities for context gathering."""

from __future__ import annotations


def is_frontend_task(raw_request: str) -> bool:
    """Detect if task involves frontend/UI work."""
    frontend_keywords = [
        "frontend",
        "ui",
        "ux",
        "component",
        "page",
        "layout",
        "design",
        "button",
        "form",
        "modal",
        "dialog",
        "style",
        "css",
        "tailwind",
        "react",
        "next",
        "tsx",
        "jsx",
        "dashboard",
        "screen",
        "view",
    ]
    lower_request = raw_request.lower()
    return any(kw in lower_request for kw in frontend_keywords)


def gather_memory_context(project_id: str, limit: int = 10) -> str:
    """Gather context from memory system.

    Memory system has been moved to Agent Hub's shared semantic memory service.
    This function returns empty string for backward compatibility.

    Args:
        project_id: Project ID
        limit: Maximum number of items to include (unused)

    Returns:
        Empty string - memory now handled by Agent Hub.
    """
    # Memory system removed - functionality moved to Agent Hub
    return ""
