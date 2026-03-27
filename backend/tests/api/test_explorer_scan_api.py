"""Tests for Explorer scan status, overview, and trigger endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.services.explorer.scan_ops import ScanAlreadyRunningError


class TestExplorerScanStatusEndpoint:
    """Tests for GET /api/projects/{project_id}/explorer/scan/status."""

    def test_returns_scan_status(self, client: TestClient) -> None:
        expected = {
            "status": "running",
            "current_type": "file",
            "types_total": 7,
            "types_completed": 2,
            "progress_pct": 28,
            "started_at": "2026-03-11T12:00:00+00:00",
            "completed_at": None,
            "error": None,
            "results": [],
        }

        with patch("app.api.explorer.validate_project_exists"), patch(
            "app.api.explorer.explorer.get_scan_status",
            return_value=expected,
        ):
            response = client.get("/api/projects/summitflow/explorer/scan/status")

        assert response.status_code == 200
        assert response.json() == expected


class TestExplorerOverviewEndpoint:
    """Tests for GET /api/projects/{project_id}/explorer/overview."""

    def test_returns_scan_overview(self, client: TestClient) -> None:
        expected = {
            "scan_status": {"status": "idle"},
            "latest_scan": {"id": 12, "status": "completed"},
            "last_completed_scan": {"id": 12, "status": "completed"},
            "history_summary": {"total_scans": 4},
            "type_summaries": {
                "file": {
                    "total": 10,
                    "by_health": {"healthy": 8, "warning": 2},
                    "last_scanned": "2026-03-11T12:00:00+00:00",
                }
            },
            "symbol_stats": {"count": 21, "last_updated": "2026-03-11T12:00:00+00:00"},
            "stale_metadata_count": 3,
        }

        with patch("app.api.explorer.validate_project_exists"), patch(
            "app.api.explorer.explorer.get_scan_overview",
            return_value=expected,
        ):
            response = client.get("/api/projects/summitflow/explorer/overview")

        assert response.status_code == 200
        assert response.json() == expected


class TestExplorerTriggerScanEndpoint:
    """Tests for POST /api/projects/{project_id}/explorer/scan."""

    def test_returns_409_when_scan_already_running(self, client: TestClient) -> None:
        current_status = {
            "status": "running",
            "current_type": "page",
            "types_total": 1,
            "types_completed": 0,
            "progress_pct": 0,
            "started_at": "2026-03-11T12:00:00+00:00",
            "completed_at": None,
            "error": None,
            "results": [],
        }

        with patch("app.api.explorer.validate_project_exists"), patch(
            "app.api.explorer.explorer.ensure_scan_not_running",
            side_effect=ScanAlreadyRunningError(current_status),
        ):
            response = client.post("/api/projects/summitflow/explorer/scan")

        assert response.status_code == 409
        assert response.json()["message"] == "Explorer scan already running"
        assert response.json()["scan_status"] == current_status

    def test_sync_regenerate_runs_off_event_loop(self, client: TestClient) -> None:
        result = {"closed_count": 1, "created_count": 2, "scanned_count": 3, "retired_count": 0}
        to_thread = AsyncMock(return_value=result)

        with (
            patch("app.api.explorer.validate_project_exists"),
            patch("app.api.explorer.asyncio.to_thread", to_thread),
            patch("app.api.explorer.regenerate_refactor_tasks_sync", create=True),
        ):
            response = client.post(
                "/api/projects/summitflow/explorer/regenerate-refactor-tasks",
                params={"sync": "true"},
            )

        assert response.status_code == 200
        assert response.json() == {"status": "completed", "project_id": "summitflow", **result}
        to_thread.assert_awaited_once()
