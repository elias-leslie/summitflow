"""Explorer context collector."""

from __future__ import annotations

import logging

from ...storage.explorer_entries import get_entries
from .token_utils import MAX_EXPLORER_TOKENS, truncate_to_tokens

logger = logging.getLogger(__name__)


def _collect_files(project_id: str, query_lower: str) -> str | None:
    """Return formatted relevant-files section, or None on failure/empty."""
    try:
        files = get_entries(project_id, filters={"entry_type": "file"})
        relevant = [
            f
            for f in files
            if query_lower in f.get("name", "").lower()
            or query_lower in f.get("path", "").lower()
        ][:20]
        if not relevant:
            return None
        lines = ["## Relevant Files\n"] + [f"- {f.get('path', 'unknown')}" for f in relevant]
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Failed to get files for %s: %s", project_id, e)
        return None


def _collect_endpoints(project_id: str) -> str | None:
    """Return formatted API-endpoints section, or None on failure/empty."""
    try:
        endpoints = get_entries(project_id, filters={"entry_type": "endpoint"})
        if not endpoints:
            return None
        lines = ["## API Endpoints\n"]
        for ep in endpoints[:20]:
            method = ep.get("metadata", {}).get("method", "GET")
            path = ep.get("path", "unknown")
            lines.append(f"- {method} {path}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Failed to get endpoints for %s: %s", project_id, e)
        return None


def _collect_tables(project_id: str) -> str | None:
    """Return formatted database-tables section, or None on failure/empty."""
    try:
        tables = get_entries(project_id, filters={"entry_type": "table"})
        if not tables:
            return None
        lines = ["## Database Tables\n"] + [f"- {t.get('name', 'unknown')}" for t in tables[:15]]
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Failed to get tables for %s: %s", project_id, e)
        return None


def gather_explorer_context(project_id: str, query: str) -> str:
    """Gather relevant explorer entries based on query.

    Args:
        project_id: Project ID
        query: Search query to find relevant entries

    Returns:
        Explorer context as string.
    """
    query_lower = query.lower()
    sections = [
        _collect_files(project_id, query_lower),
        _collect_endpoints(project_id),
        _collect_tables(project_id),
    ]
    combined = "\n\n".join(s for s in sections if s)
    return truncate_to_tokens(combined, MAX_EXPLORER_TOKENS)
