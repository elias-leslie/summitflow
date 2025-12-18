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

import threading
import time
from dataclasses import dataclass, field
from typing import Literal

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
# Scan State Tracking
# ============================================================================

ScanStatus = Literal["idle", "scanning", "complete", "error"]


@dataclass
class ScanState:
    """Track scan progress for a project."""

    status: ScanStatus = "idle"
    current_type: str | None = None
    types_total: int = 0
    types_completed: int = 0
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    results: list[ScanResult] = field(default_factory=list)


# In-memory scan state keyed by project_id
# Thread-safe access via _scan_lock
_scan_states: dict[str, ScanState] = {}
_scan_lock = threading.Lock()


def get_scan_status(project_id: str) -> dict:
    """Get current scan status for a project.

    Returns:
        Dict with status, progress, and timing info
    """
    with _scan_lock:
        state = _scan_states.get(project_id, ScanState())

    return {
        "status": state.status,
        "current_type": state.current_type,
        "types_total": state.types_total,
        "types_completed": state.types_completed,
        "progress_pct": (
            int(state.types_completed / state.types_total * 100) if state.types_total > 0 else 0
        ),
        "started_at": state.started_at,
        "completed_at": state.completed_at,
        "error": state.error,
        "results": [
            {
                "entry_type": r.entry_type,
                "entries_found": r.entries_found,
                "entries_saved": r.entries_saved,
                "duration_ms": r.duration_ms,
                "success": r.success,
            }
            for r in state.results
        ],
    }


def _clear_scan_state(project_id: str) -> None:
    """Clear scan state for a project (called after frontend acknowledges completion)."""
    with _scan_lock:
        _scan_states.pop(project_id, None)


def start_scan(project_id: str, entry_type: str | None = None) -> dict:
    """Start a scan and track its state.

    Args:
        project_id: Project to scan
        entry_type: Optional specific type to scan (scans all if None)

    Returns:
        Initial status dict
    """
    types_to_scan = [entry_type] if entry_type else list_registered_types()

    with _scan_lock:
        _scan_states[project_id] = ScanState(
            status="scanning",
            types_total=len(types_to_scan),
            types_completed=0,
            started_at=time.time(),
            results=[],
        )

    return get_scan_status(project_id)


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


def run_scan_with_tracking(project_id: str, entry_type: str | None = None) -> None:
    """Run scan with progress tracking (for background tasks).

    Updates scan state as each type completes. Called from API background task.

    Args:
        project_id: Project to scan
        entry_type: Optional specific type (scans all if None)
    """
    types_to_scan = [entry_type] if entry_type else list_registered_types()

    for t in types_to_scan:
        # Update current type being scanned
        with _scan_lock:
            state = _scan_states.get(project_id)
            if state:
                state.current_type = t

        # Run the scan
        result = scan(project_id, t)

        # Record result and update progress
        with _scan_lock:
            state = _scan_states.get(project_id)
            if state:
                state.results.append(result)
                state.types_completed += 1
                state.current_type = None

                if not result.success and state.status != "error":
                    state.error = result.error

    # Mark scan complete
    with _scan_lock:
        state = _scan_states.get(project_id)
        if state:
            state.status = "complete" if not state.error else "error"
            state.completed_at = time.time()


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
