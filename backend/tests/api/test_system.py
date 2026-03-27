"""Tests for system observability endpoints."""

from __future__ import annotations

from datetime import UTC, datetime


def test_get_system_resources_returns_all_monitored_disks(client, mocker) -> None:
    """System stats expose the root disk plus any extra monitored mounts."""
    mocker.patch(
        "app.api.system.get_disk_usages",
        return_value=[
            {
                "label": "Root",
                "mount_path": "/",
                "total_gb": 96.84,
                "used_gb": 43.6,
                "free_gb": 53.24,
                "percent_used": 45.03,
                "status": "ok",
            },
            {
                "label": "Workspaces",
                "mount_path": "/srv/workspaces",
                "total_gb": 200.0,
                "used_gb": 7.1,
                "free_gb": 192.9,
                "percent_used": 3.55,
                "status": "ok",
            },
        ],
    )
    mocker.patch(
        "app.api.system.get_memory_usage",
        return_value={
            "total_gb": 62.56,
            "used_gb": 20.4,
            "available_gb": 42.16,
            "percent_used": 32.6,
            "status": "ok",
        },
    )
    mocker.patch(
        "app.api.system.get_cpu_usage",
        return_value={"percent_used": 1.6, "cores": 8, "status": "ok"},
    )

    response = client.get("/api/system/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["disk"]["mount_path"] == "/"
    assert [disk["mount_path"] for disk in payload["disks"]] == [
        "/",
        "/srv/workspaces",
    ]
    assert payload["disks"][1]["label"] == "Workspaces"


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
