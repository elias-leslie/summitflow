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
    mocker.patch(
        "app.api.autonomous._make_dispatch_callback",
        return_value=lambda _stage, _task_id, _project_id: None,
    )
    run_upkeep = mocker.patch(
        "app.api.autonomous.run_routine_upkeep",
        return_value={
            "project_id": ensure_test_project,
            "status": "completed",
            "tasks_created": 2,
            "dispatch": {"dispatched": 2, "breakdown": {"execution": 2}},
        },
    )

    response = client.post(f"/api/projects/{ensure_test_project}/autonomous/upkeep/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["tasks_created"] == 2
    run_upkeep.assert_called_once()
    assert run_upkeep.call_args.kwargs["force"] is True
