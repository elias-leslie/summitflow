"""Tests for routine upkeep API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime


def _run_row(status: str = "completed") -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "id": 1,
        "workflow_name": "routine_upkeep",
        "status": status,
        "started_at": now,
        "finished_at": now,
        "duration_ms": 120,
        "rows_cleaned": 2,
        "summary": {"tasks_created": 1, "dispatch": {"dispatched": 1}},
        "error_message": None,
        "created_at": now,
    }


def test_get_routine_upkeep_status(client, ensure_test_project, mocker) -> None:
    mocker.patch(
        "app.api.autonomous.get_routine_upkeep_settings",
        return_value=mocker.Mock(enabled=True, frequency_minutes=120, batch_limit=5),
    )
    list_runs = mocker.patch(
        "app.api.autonomous.maintenance_store.list_maintenance_runs",
        return_value=[_run_row()],
    )

    response = client.get(f"/api/projects/{ensure_test_project}/autonomous/upkeep/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["enabled"] is True
    assert payload["settings"]["frequency_minutes"] == 120
    assert payload["latest"]["workflow_name"] == "routine_upkeep"
    assert payload["recent"][0]["summary"]["tasks_created"] == 1
    list_runs.assert_called_once_with(
        limit=5,
        workflow_name="routine_upkeep",
        project_id=ensure_test_project,
    )


def test_manual_routine_upkeep_run_returns_summary(client, ensure_test_project, mocker) -> None:
    run_upkeep = mocker.patch(
        "app.api.autonomous.run_routine_upkeep",
        return_value={
            "project_id": ensure_test_project,
            "status": "completed",
            "tasks_created": 2,
            "dispatch": {"dispatched": 0, "message": "discovery_only"},
        },
    )

    response = client.post(f"/api/projects/{ensure_test_project}/autonomous/upkeep/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["tasks_created"] == 2
    run_upkeep.assert_called_once()
    assert run_upkeep.call_args.kwargs["force"] is True


def test_get_autonomous_schedules_returns_registry_state(client, ensure_test_project, mocker) -> None:
    list_schedules = mocker.patch(
        "app.api.autonomous.list_autonomous_schedule_states",
        return_value=[
            {
                "schedule_id": "work_pickup",
                "config_key": "work_pickup_enabled",
                "label": "Autonomous work pickup",
                "description": "Dispatches pending autonomous tasks.",
                "cron": "15 */2 * * *",
                "scope": "project",
                "default_enabled": True,
                "enabled": False,
                "managed_project_id": ensure_test_project,
            }
        ],
    )

    response = client.get(f"/api/projects/{ensure_test_project}/autonomous/schedules")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["schedule_id"] == "work_pickup"
    assert payload[0]["enabled"] is False
    list_schedules.assert_called_once_with(ensure_test_project)


def test_update_autonomous_schedule_toggles_registry_state(client, ensure_test_project, mocker) -> None:
    update_schedule = mocker.patch(
        "app.api.autonomous.set_autonomous_schedule_enabled",
        return_value={
            "schedule_id": "work_pickup",
            "config_key": "work_pickup_enabled",
            "label": "Autonomous work pickup",
            "description": "Dispatches pending autonomous tasks.",
            "cron": "15 */2 * * *",
            "scope": "project",
            "default_enabled": True,
            "enabled": False,
            "managed_project_id": ensure_test_project,
        },
    )

    response = client.patch(
        f"/api/projects/{ensure_test_project}/autonomous/schedules/work_pickup",
        json={"enabled": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schedule_id"] == "work_pickup"
    assert payload["enabled"] is False
    update_schedule.assert_called_once_with(
        ensure_test_project,
        "work_pickup",
        enabled=False,
    )
