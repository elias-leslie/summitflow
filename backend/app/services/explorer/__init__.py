"""Explorer service - Unified codebase exploration.

Public interface for Explorer functionality:
- scan(): Trigger scan for a project and entry type
- get_entries(): Get entries with filters
- get_stats(): Get aggregated statistics

Usage:
    from app.services.explorer import scan, get_entries, get_stats

    # Scan files for a project
    result = scan("portfolio-ai", "file")

    # Get all file entries
    entries = get_entries("portfolio-ai", {"type": "file"})

    # Get statistics
    stats = get_stats("portfolio-ai")
"""

from __future__ import annotations

from ...storage import explorer as storage
from .base import BaseScanner, get_project_config, get_project_root
from .health import calculate_health
from .models import (
    ExplorerEntry,
    ExplorerEntryCreate,
    ExplorerFilters,
    ExplorerRelationship,
    ExplorerStats,
    ScanResult,
)
from .types import get_scanner

__all__ = [
    # Models
    "ExplorerEntry",
    "ExplorerEntryCreate",
    "ExplorerFilters",
    "ExplorerRelationship",
    "ExplorerStats",
    "ScanResult",
    # Base
    "BaseScanner",
    "get_project_root",
    "get_project_config",
    # Health
    "calculate_health",
    # Public functions
    "scan",
    "get_entries",
    "get_entry",
    "get_children",
    "get_stats",
]


def scan(project_id: str, entry_type: str, config: dict | None = None) -> ScanResult:
    """Trigger a scan for a project and entry type.

    Args:
        project_id: Project ID to scan
        entry_type: Type to scan ('file', 'table', 'task', 'endpoint')
        config: Optional type-specific configuration

    Returns:
        ScanResult with scan statistics

    Raises:
        ValueError: If entry_type is not registered
    """
    scanner_class = get_scanner(entry_type)
    if not scanner_class:
        return ScanResult(
            success=False,
            entry_type=entry_type,
            error=f"Unknown entry type: {entry_type}",
        )

    scanner = scanner_class(project_id, config)
    return scanner.run()


def get_entries(project_id: str, filters: dict | None = None) -> list[dict]:
    """Get explorer entries with optional filters.

    Args:
        project_id: Project ID for scoping
        filters: Optional filter dict (see storage.get_entries)

    Returns:
        List of entry dicts
    """
    return storage.get_entries(project_id, filters)


def get_entry(project_id: str, entry_type: str, path: str) -> dict | None:
    """Get a single explorer entry.

    Args:
        project_id: Project ID for scoping
        entry_type: Entry type
        path: Entry path

    Returns:
        Entry dict or None
    """
    return storage.get_entry(project_id, entry_type, path)


def get_children(project_id: str, entry_type: str, parent_path: str = "") -> list[dict]:
    """Get direct children for tree navigation.

    Args:
        project_id: Project ID for scoping
        entry_type: Entry type
        parent_path: Parent path (empty for root)

    Returns:
        List of child entry dicts
    """
    return storage.get_children(project_id, entry_type, parent_path)


def get_stats(project_id: str, entry_type: str | None = None) -> dict:
    """Get aggregated statistics.

    Args:
        project_id: Project ID for scoping
        entry_type: Optional entry type to filter stats by

    Returns:
        Stats dict with by_type, by_health, total, last_scanned
    """
    return storage.get_stats(project_id, entry_type)
