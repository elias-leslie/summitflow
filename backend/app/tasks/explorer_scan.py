"""Explorer scan utilities for project scanning."""

from __future__ import annotations

from typing import Any

from ..services import explorer


def scan_project(project_id: str, entry_type: str | None = None) -> list[dict[str, Any]]:
    """Scan a single project and return results.

    Args:
        project_id: Project to scan
        entry_type: Optional specific type (None = all types)

    Returns:
        List of scan results for each entry type
    """
    from ..services.explorer.types import list_registered_types

    types_to_scan = [entry_type] if entry_type else list_registered_types()
    results = []

    for t in types_to_scan:
        result = explorer.scan(project_id, t)
        results.append(
            {
                "entry_type": result.entry_type,
                "entries_found": result.entries_found,
                "entries_saved": result.entries_saved,
                "duration_ms": result.duration_ms,
                "success": result.success,
                "error": result.error,
            }
        )

    return results
