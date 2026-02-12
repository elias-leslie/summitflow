"""Explorer service - Unified codebase exploration.

Public interface for Explorer functionality:
- scan(): Trigger scan for a project and entry type
- get_entries(): Get entries with filters
- get_stats(): Get aggregated statistics
- get_scan_status(): Get current scan status for polling

Usage:
    from app.services.explorer import scan, get_entries, get_stats, get_scan_status

    # Scan files for a project
    result = scan("portfolio-ai", "file")

    # Get all file entries
    entries = get_entries("portfolio-ai", {"type": "file"})

    # Get statistics
    stats = get_stats("portfolio-ai")

    # Check scan status
    status = get_scan_status("portfolio-ai")
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from ...storage import explorer as storage
from .base import BaseScanner, get_project_config, get_project_root
from .health import calculate_health
from .index_generator import generate_index, write_all_index_files, write_index_file
from .models import (
    ExplorerEntry,
    ExplorerEntryCreate,
    ExplorerFilters,
    ExplorerRelationship,
    ExplorerStats,
    ScanResult,
)
from .types import get_scanner, list_registered_types

__all__ = [
    "BaseScanner",
    "ExplorerEntry",
    "ExplorerEntryCreate",
    "ExplorerFilters",
    "ExplorerRelationship",
    "ExplorerStats",
    "ScanResult",
    "calculate_health",
    "generate_index",
    "get_children",
    "get_entries",
    "get_entry",
    "get_project_config",
    "get_project_root",
    "get_stats",
    "run_scan_with_tracking",
    "scan",
    "write_all_index_files",
    "write_index_file",
]


# ============================================================================
# Scan execution (simplified - no state tracking)
# ============================================================================


def scan(project_id: str, entry_type: str, config: dict[str, Any] | None = None) -> ScanResult:
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


def run_scan_with_tracking(project_id: str, entry_type: str | None = None) -> None:
    """Run scan for background tasks.

    Args:
        project_id: Project to scan
        entry_type: Optional specific type (scans all if None)
    """
    types_to_scan = [entry_type] if entry_type else list_registered_types()
    error_msg: str | None = None

    for t in types_to_scan:
        result = scan(project_id, t)
        if not result.success and error_msg is None:
            error_msg = result.error

    # Generate index file at project root on successful scan
    if not error_msg:
        write_index_file(project_id)


def get_entries(project_id: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Get explorer entries with optional filters.

    Args:
        project_id: Project ID for scoping
        filters: Optional filter dict (see storage.get_entries)

    Returns:
        List of entry dicts
    """
    return storage.get_entries(project_id, filters)


def get_entry(project_id: str, entry_type: str, path: str) -> dict[str, Any] | None:
    """Get a single explorer entry.

    Args:
        project_id: Project ID for scoping
        entry_type: Entry type
        path: Entry path

    Returns:
        Entry dict or None
    """
    return storage.get_entry(project_id, entry_type, path)


def get_children(project_id: str, entry_type: str, parent_path: str = "") -> list[dict[str, Any]]:
    """Get direct children for tree navigation.

    Args:
        project_id: Project ID for scoping
        entry_type: Entry type
        parent_path: Parent path (empty for root)

    Returns:
        List of child entry dicts
    """
    return storage.get_children(project_id, entry_type, parent_path)


def get_stats(project_id: str, entry_type: str | None = None) -> dict[str, Any]:
    """Get aggregated statistics.

    Args:
        project_id: Project ID for scoping
        entry_type: Optional entry type to filter stats by

    Returns:
        Stats dict with by_type, by_health, total, last_scanned
    """
    return storage.get_stats(project_id, entry_type)
