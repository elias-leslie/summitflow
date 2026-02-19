"""Scan state tracking for Explorer service.

Handles scan lifecycle: starting, progress tracking, and completion.
Persists state to database for resilience across backend restarts.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ...storage import explorer as storage
from .constants import (
    SCAN_STATUS_COMPLETED,
    SCAN_STATUS_FAILED,
    SCAN_STATUS_IDLE,
    SCAN_STATUS_RUNNING,
)
from .index_generator import write_index_file
from .models import ScanResult
from .types import list_registered_types

ScanFn = Callable[[str, str], ScanResult]

# Default scan status when no state exists
_DEFAULT_STATUS: dict[str, Any] = {
    "status": SCAN_STATUS_IDLE,
    "current_type": None,
    "types_total": 0,
    "types_completed": 0,
    "progress_pct": 0,
    "started_at": None,
    "completed_at": None,
    "error": None,
    "results": [],
}


def _calc_progress(types_completed: int, types_total: int) -> int:
    """Calculate progress percentage from completed/total counts."""
    if types_total <= 0:
        return 0
    return int(types_completed / types_total * 100)


def _parse_started_at(state: dict[str, Any] | None) -> datetime:
    """Parse started_at from scan state, falling back to now."""
    if state and state.get("started_at"):
        return datetime.fromisoformat(str(state["started_at"]))
    return datetime.now(UTC)


def _result_to_dict(result: ScanResult) -> dict[str, Any]:
    """Convert a ScanResult to a plain dict for storage."""
    return {
        "entry_type": result.entry_type,
        "entries_found": result.entries_found,
        "entries_saved": result.entries_saved,
        "duration_ms": result.duration_ms,
        "success": result.success,
    }


def get_scan_status(project_id: str) -> dict[str, Any]:
    """Get current scan status for a project.

    Reads from database for persistence across backend restarts.

    Returns:
        Dict with status, progress, and timing info
    """
    state = storage.get_scan_state(project_id)
    if not state:
        return dict(_DEFAULT_STATUS)

    types_total = int(state.get("types_total") or 0)
    types_completed = int(state.get("types_completed") or 0)
    return {
        "status": state.get("status", SCAN_STATUS_IDLE),
        "current_type": state.get("current_type"),
        "types_total": types_total,
        "types_completed": types_completed,
        "progress_pct": _calc_progress(types_completed, types_total),
        "started_at": state.get("started_at"),
        "completed_at": state.get("completed_at"),
        "error": state.get("error"),
        "results": (state.get("results") or {}).get("scans", []),
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
        status=SCAN_STATUS_RUNNING,
        types_total=len(types_to_scan),
        types_completed=0,
        started_at=datetime.now(UTC),
        results={"scans": []},
    )
    return get_scan_status(project_id)


def _update_type_progress(
    project_id: str,
    current_type: str,
    types_total: int,
    types_completed: int,
    scan_results: list[dict[str, Any]],
    started_at: datetime,
) -> None:
    """Update scan state while a type is being scanned."""
    storage.update_scan_state(
        project_id=project_id,
        status=SCAN_STATUS_RUNNING,
        current_type=current_type,
        types_total=types_total,
        types_completed=types_completed,
        started_at=started_at,
        results={"scans": scan_results},
    )


def _finalize_scan(
    project_id: str,
    types_total: int,
    types_completed: int,
    scan_results: list[dict[str, Any]],
    started_at: datetime,
    error_msg: str | None,
) -> None:
    """Finalize the scan state and generate index if successful."""
    final_status = SCAN_STATUS_COMPLETED if not error_msg else SCAN_STATUS_FAILED
    storage.update_scan_state(
        project_id=project_id,
        status=final_status,
        current_type=None,
        types_total=types_total,
        types_completed=types_completed,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        error=error_msg,
        results={"scans": scan_results},
    )
    if not error_msg:
        write_index_file(project_id)


def run_scan_with_tracking(
    project_id: str,
    entry_type: str | None,
    scan_fn: ScanFn,
) -> None:
    """Run scan with progress tracking (for background tasks).

    Updates scan state in database as each type completes.
    Called from API background task.

    Args:
        project_id: Project to scan
        entry_type: Optional specific type (scans all if None)
        scan_fn: Callable(project_id, entry_type) -> ScanResult
    """
    types_to_scan = [entry_type] if entry_type else list_registered_types()
    scan_results: list[dict[str, Any]] = []
    error_msg: str | None = None

    current_state = storage.get_scan_state(project_id)
    types_total = (
        int(current_state.get("types_total") or len(types_to_scan))
        if current_state
        else len(types_to_scan)
    )
    started_at = _parse_started_at(current_state)

    for i, t in enumerate(types_to_scan):
        _update_type_progress(project_id, t, types_total, i, scan_results, started_at)
        result = scan_fn(project_id, t)
        scan_results.append(_result_to_dict(result))
        if not result.success and error_msg is None:
            error_msg = result.error

    _finalize_scan(project_id, types_total, len(types_to_scan), scan_results, started_at, error_msg)
