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
    # Base
    "BaseScanner",
    # Models
    "ExplorerEntry",
    "ExplorerEntryCreate",
    "ExplorerFilters",
    "ExplorerRelationship",
    "ExplorerStats",
    "ScanResult",
    # Health
    "calculate_health",
    "get_children",
    "get_entries",
    "get_entry",
    "get_project_config",
    "get_project_root",
    "get_scan_status",
    "get_stats",
    "run_scan_with_tracking",
    # Public functions
    "scan",
    "start_scan",
]


# ============================================================================
# Scan State Tracking (persisted to database)
# ============================================================================

ScanStatus = Literal["idle", "running", "completed", "failed"]


def get_scan_status(project_id: str) -> dict[str, Any]:
    """Get current scan status for a project.

    Reads from database for persistence across backend restarts.

    Returns:
        Dict with status, progress, and timing info
    """
    state = storage.get_scan_state(project_id)

    if not state:
        return {
            "status": "idle",
            "current_type": None,
            "types_total": 0,
            "types_completed": 0,
            "progress_pct": 0,
            "started_at": None,
            "completed_at": None,
            "error": None,
            "results": [],
        }

    types_total = state.get("types_total", 0)
    types_completed = state.get("types_completed", 0)

    return {
        "status": state.get("status", "idle"),
        "current_type": state.get("current_type"),
        "types_total": types_total,
        "types_completed": types_completed,
        "progress_pct": int(types_completed / types_total * 100) if types_total > 0 else 0,
        "started_at": state.get("started_at"),
        "completed_at": state.get("completed_at"),
        "error": state.get("error"),
        "results": state.get("results", {}).get("scans", []),
    }


def start_scan(project_id: str, entry_type: str | None = None) -> dict[str, Any]:
    """Start a scan and track its state.

    Persists state to database for resilience across restarts.

    Args:
        project_id: Project to scan
        entry_type: Optional specific type to scan (scans all if None)

    Returns:
        Initial status dict
    """
    types_to_scan = [entry_type] if entry_type else list_registered_types()

    storage.update_scan_state(
        project_id=project_id,
        status="running",
        types_total=len(types_to_scan),
        types_completed=0,
        started_at=datetime.now(UTC),
        results={"scans": []},
    )

    return get_scan_status(project_id)


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
    """Run scan with progress tracking (for background tasks).

    Updates scan state in database as each type completes. Persists across restarts.
    Called from API background task.

    Args:
        project_id: Project to scan
        entry_type: Optional specific type (scans all if None)
    """
    types_to_scan = [entry_type] if entry_type else list_registered_types()
    scan_results: list[dict[str, Any]] = []
    error_msg: str | None = None

    # Get current state to preserve types_total
    current_state = storage.get_scan_state(project_id)
    types_total = (
        current_state.get("types_total", len(types_to_scan))
        if current_state
        else len(types_to_scan)
    )

    for i, t in enumerate(types_to_scan):
        # Update current type being scanned
        storage.update_scan_state(
            project_id=project_id,
            status="running",
            current_type=t,
            types_total=types_total,
            types_completed=i,
            started_at=datetime.fromisoformat(current_state["started_at"])
            if current_state and current_state.get("started_at")
            else datetime.now(UTC),
            results={"scans": scan_results},
        )

        # Run the scan
        result = scan(project_id, t)

        # Record result
        scan_results.append(
            {
                "entry_type": result.entry_type,
                "entries_found": result.entries_found,
                "entries_saved": result.entries_saved,
                "duration_ms": result.duration_ms,
                "success": result.success,
            }
        )

        if not result.success and error_msg is None:
            error_msg = result.error

    # Mark scan complete
    storage.update_scan_state(
        project_id=project_id,
        status="completed" if not error_msg else "failed",
        current_type=None,
        types_total=types_total,
        types_completed=len(types_to_scan),
        started_at=datetime.fromisoformat(current_state["started_at"])
        if current_state and current_state.get("started_at")
        else datetime.now(UTC),
        completed_at=datetime.now(UTC),
        error=error_msg,
        results={"scans": scan_results},
    )


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
