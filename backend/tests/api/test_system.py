"""Tests for system observability endpoints."""

from __future__ import annotations

from datetime import UTC, datetime


def test_get_maintenance_status_returns_latest_and_recent_runs(client, mocker) -> None:
    """Maintenance endpoint exposes the latest workflow runs and recent history."""
    now = datetime.now(UTC)
    latest_run = {
        "id": 11,
        "workflow_name": "daily_maintenance",
        "status": "partial",
        "started_at": now,
        "finished_at": now,
        "duration_ms": 1250,
        "rows_cleaned": 42,
        "summary": {"events_deleted": {"total_deleted": 8}},
        "error_message": None,
        "created_at": now,
    }
    recent_run = {
        "id": 12,
        "workflow_name": "scheduled_backups",
        "status": "success",
        "started_at": now,
        "finished_at": now,
        "duration_ms": 500,
        "rows_cleaned": 3,
        "summary": {"expired_cleaned": 3},
        "error_message": None,
        "created_at": now,
    }
    mocker.patch(
        "app.api.system.maintenance_store.get_latest_maintenance_runs",
        return_value={"daily_maintenance": latest_run},
    )
    mocker.patch(
        "app.api.system.maintenance_store.list_maintenance_runs",
        return_value=[latest_run, recent_run],
    )

    response = client.get("/api/system/maintenance?limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["latest"]["daily_maintenance"]["rows_cleaned"] == 42
    assert payload["latest"]["daily_maintenance"]["summary"]["events_deleted"]["total_deleted"] == 8
    assert [run["workflow_name"] for run in payload["recent"]] == [
        "daily_maintenance",
        "scheduled_backups",
    ]
