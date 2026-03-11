"""Tests for Explorer scan orchestration helpers."""

from __future__ import annotations

from unittest.mock import patch

from app.services.explorer.scan_ops import (
    ScanAlreadyRunningError,
    build_scan_metrics,
    get_scan_overview,
)


class TestBuildScanMetrics:
    """Tests for scan metric aggregation."""

    def test_builds_metrics_from_current_explorer_state(self) -> None:
        with (
            patch(
                "app.services.explorer.scan_ops.storage.get_scan_metrics",
                return_value={
                    "complexity": 321.5,
                    "high_priority_count": 4,
                    "medium_priority_count": 7,
                },
            ),
            patch(
                "app.services.explorer.scan_ops.storage.get_type_summaries",
                return_value={"file": {"total": 12}, "page": {"total": 3}},
            ),
            patch(
                "app.services.explorer.scan_ops.storage.get_symbol_stats",
                return_value={"count": 44, "last_updated": "2026-03-11T12:00:00+00:00"},
            ),
            patch(
                "app.services.explorer.scan_ops.storage.count_stale_metadata_entries",
                return_value=2,
            ),
        ):
            metrics = build_scan_metrics("summitflow", [{"entry_type": "file"}, {"entry_type": "page"}])

        assert metrics["types_scanned"] == 2
        assert metrics["complexity"] == 321.5
        assert metrics["high_priority_count"] == 4
        assert metrics["medium_priority_count"] == 7
        assert metrics["symbol_count"] == 44
        assert metrics["stale_metadata_count"] == 2
        assert metrics["entry_counts"] == {"file": 12, "page": 3}


class TestGetScanOverview:
    """Tests for Explorer overview aggregation."""

    def test_returns_aggregated_overview(self) -> None:
        with (
            patch(
                "app.services.explorer.scan_ops.get_scan_status",
                return_value={"status": "completed"},
            ),
            patch(
                "app.services.explorer.scan_ops.scan_history.get_latest_scan",
                side_effect=[
                    {"id": 9, "status": "failed"},
                    {"id": 8, "status": "completed"},
                ],
            ),
            patch(
                "app.services.explorer.scan_ops.scan_history.get_summary",
                return_value={"total_scans": 6},
            ),
            patch(
                "app.services.explorer.scan_ops.storage.get_type_summaries",
                return_value={"file": {"total": 10, "by_health": {}, "last_scanned": None}},
            ),
            patch(
                "app.services.explorer.scan_ops.storage.get_symbol_stats",
                return_value={"count": 19, "last_updated": None},
            ),
            patch(
                "app.services.explorer.scan_ops.storage.count_stale_metadata_entries",
                return_value=5,
            ),
        ):
            overview = get_scan_overview("summitflow")

        assert overview["scan_status"] == {"status": "completed"}
        assert overview["latest_scan"] == {"id": 9, "status": "failed"}
        assert overview["last_completed_scan"] == {"id": 8, "status": "completed"}
        assert overview["history_summary"] == {"total_scans": 6}
        assert overview["type_summaries"]["file"]["total"] == 10
        assert overview["symbol_stats"]["count"] == 19
        assert overview["stale_metadata_count"] == 5


class TestScanAlreadyRunningError:
    """Tests for the concurrency guard exception."""

    def test_preserves_current_status(self) -> None:
        status = {"status": "running", "current_type": "file"}

        error = ScanAlreadyRunningError(status)

        assert error.scan_status == status
