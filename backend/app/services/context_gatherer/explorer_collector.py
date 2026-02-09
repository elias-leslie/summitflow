"""Explorer context collector."""

from __future__ import annotations

import logging

from ...storage.explorer_entries import get_entries
from .token_utils import MAX_EXPLORER_TOKENS, truncate_to_tokens

logger = logging.getLogger(__name__)


def gather_explorer_context(project_id: str, query: str) -> str:
    """Gather relevant explorer entries based on query.

    Args:
        project_id: Project ID
        query: Search query to find relevant entries

    Returns:
        Explorer context as string.
    """
    result_parts: list[str] = []

    # Query keywords for filtering
    query_lower = query.lower()

    # Get files
    try:
        files = get_entries(project_id, filters={"entry_type": "file"})
        relevant_files = [
            f
            for f in files
            if query_lower in f.get("name", "").lower() or query_lower in f.get("path", "").lower()
        ][:20]

        if relevant_files:
            file_lines = ["## Relevant Files\n"]
            for f in relevant_files:
                path = f.get("path", "unknown")
                file_lines.append(f"- {path}")
            result_parts.append("\n".join(file_lines))
    except Exception as e:
        logger.warning("Failed to get files for %s: %s", project_id, e)

    # Get endpoints
    try:
        endpoints = get_entries(project_id, filters={"entry_type": "endpoint"})
        if endpoints:
            endpoint_lines = ["## API Endpoints\n"]
            for ep in endpoints[:20]:
                method = ep.get("metadata", {}).get("method", "GET")
                path = ep.get("path", "unknown")
                endpoint_lines.append(f"- {method} {path}")
            result_parts.append("\n".join(endpoint_lines))
    except Exception as e:
        logger.warning("Failed to get endpoints for %s: %s", project_id, e)

    # Get database tables
    try:
        tables = get_entries(project_id, filters={"entry_type": "table"})
        if tables:
            table_lines = ["## Database Tables\n"]
            for t in tables[:15]:
                name = t.get("name", "unknown")
                table_lines.append(f"- {name}")
            result_parts.append("\n".join(table_lines))
    except Exception as e:
        logger.warning("Failed to get tables for %s: %s", project_id, e)

    combined = "\n\n".join(result_parts)
    return truncate_to_tokens(combined, MAX_EXPLORER_TOKENS)
