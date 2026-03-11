"""Canonical Explorer scan orchestration and overview helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...storage import explorer as storage
from ...storage import scan_history
from ._scan_tracking import (
    get_scan_status,
    start_scan,
)
from ._scan_tracking import (
    run_scan_with_tracking as run_scan_with_tracking_impl,
)
from .constants import SCAN_STATUS_FAILED, SCAN_STATUS_RUNNING
from .models import ScanResult
from .types import get_scanner


class ScanAlreadyRunningError(RuntimeError):
    """Raised when a new scan is requested while another is still running."""

    def __init__(self, scan_status: dict[str, Any]) -> None:
        super().__init__("Explorer scan already running")
        self.scan_status = scan_status


def ensure_scan_not_running(project_id: str) -> None:
    """Reject overlapping scans for the same project."""
    status = get_scan_status(project_id)
    if status.get("status") == SCAN_STATUS_RUNNING:
        raise ScanAlreadyRunningError(status)


def build_scan_metrics(
    project_id: str,
    scan_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build durable scan metrics from the current explorer snapshot."""
    state_metrics = storage.get_scan_metrics(project_id)
    type_summaries = storage.get_type_summaries(project_id)
    symbol_stats = storage.get_symbol_stats(project_id)

    return {
        "types_scanned": len(scan_results),
        "by_type": {result["entry_type"]: result for result in scan_results},
        "complexity": state_metrics["complexity"],
        "high_priority_count": state_metrics["high_priority_count"],
        "medium_priority_count": state_metrics["medium_priority_count"],
        "entry_counts": {
            entry_type: summary["total"]
            for entry_type, summary in type_summaries.items()
        },
        "symbol_count": symbol_stats["count"],
        "stale_metadata_count": storage.count_stale_metadata_entries(project_id),
    }


def _scan_entry_type(project_id: str, entry_type: str) -> ScanResult:
    """Run one registered scanner type."""
    scanner_class = get_scanner(entry_type)
    if not scanner_class:
        return ScanResult(
            success=False,
            entry_type=entry_type,
            error=f"Unknown entry type: {entry_type}",
        )
    return scanner_class(project_id).run()


def _parse_started_at(value: str | None) -> datetime:
    if value:
        return datetime.fromisoformat(value)
    return datetime.now(UTC)


def _mark_scan_failed(project_id: str, error: str) -> None:
    """Persist a failed scan state when orchestration aborts unexpectedly."""
    current = storage.get_scan_state(project_id) or {}
    storage.update_scan_state(
        project_id=project_id,
        status=SCAN_STATUS_FAILED,
        current_type=None,
        types_total=int(current.get("types_total") or 0),
        types_completed=int(current.get("types_completed") or 0),
        started_at=_parse_started_at(current.get("started_at")),
        completed_at=datetime.now(UTC),
        error=error,
        results=(current.get("results") or {"scans": []}),
    )


def run_scan_job(
    project_id: str,
    entry_type: str | None = None,
    *,
    triggered_by: str = "manual",
    triggered_by_session: str | None = None,
    triggered_by_user: str | None = None,
    trigger_context: dict[str, Any] | None = None,
    enforce_exclusive: bool = True,
) -> dict[str, Any]:
    """Run a full Explorer scan lifecycle with tracking and history."""
    if enforce_exclusive:
        ensure_scan_not_running(project_id)

    start_scan(project_id, entry_type)
    scan_type = entry_type or "full"
    scan_id = scan_history.record_scan_start(
        project_id=project_id,
        scan_type=scan_type,
        triggered_by=triggered_by,
        triggered_by_session=triggered_by_session,
        triggered_by_user=triggered_by_user,
        trigger_context=trigger_context,
    )

    try:
        run_scan_with_tracking_impl(project_id, entry_type, _scan_entry_type)
        scan_status = get_scan_status(project_id)
        scan_results = scan_status.get("results", [])
        metrics = build_scan_metrics(project_id, scan_results)
        entries_found = sum(result.get("entries_found", 0) for result in scan_results)
        entries_saved = sum(result.get("entries_saved", 0) for result in scan_results)

        scan_history.record_scan_complete(
            scan_id=scan_id,
            status="completed" if scan_status.get("status") != SCAN_STATUS_FAILED else "failed",
            error_message=scan_status.get("error"),
            metrics=metrics,
            entries_found=entries_found,
            entries_saved=entries_saved,
        )
        return {
            **scan_status,
            "scan_id": scan_id,
            "metrics": metrics,
        }
    except Exception as exc:
        _mark_scan_failed(project_id, str(exc))
        scan_history.record_scan_complete(
            scan_id=scan_id,
            status="failed",
            error_message=str(exc),
        )
        raise


def get_scan_overview(project_id: str) -> dict[str, Any]:
    """Return the high-signal Explorer operator overview for a project."""
    return {
        "scan_status": get_scan_status(project_id),
        "latest_scan": scan_history.get_latest_scan(project_id),
        "last_completed_scan": scan_history.get_latest_scan(
            project_id,
            statuses=["completed"],
        ),
        "history_summary": scan_history.get_summary(project_id),
        "type_summaries": storage.get_type_summaries(project_id),
        "symbol_stats": storage.get_symbol_stats(project_id),
        "stale_metadata_count": storage.count_stale_metadata_entries(project_id),
    }
