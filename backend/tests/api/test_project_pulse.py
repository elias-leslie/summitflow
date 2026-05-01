"""Tests for the project pulse coordination endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


def test_get_project_pulse_returns_aggregated_coordination_payload(client) -> None:
    payload = {
        "project_id": "agent-hub",
        "generated_at": "2026-03-08T00:00:00Z",
        "summary": {
            "running_tasks": 1,
            "active_owners": 1,
            "active_specialists": 0,
            "active_sessions": 2,
            "stale_sessions": 1,
            "reapable_sessions": 1,
            "active_checkpoints": 1,
            "dirty_checkpoints": 0,
            "needs_cleanup": False,
        },
        "running_tasks": [{"id": "task-1", "title": "Refactor", "status": "running"}],
        "active_owners": [{"session_id": "sess-owner", "task_id": "task-1"}],
        "active_specialists": [],
        "active_sessions": [{"id": "sess-owner"}, {"id": "sess-observer"}],
        "stale_sessions": [{"id": "sess-stale"}],
        "cleanup": {"project_id": "agent-hub", "active_checkpoints": 1, "dirty_checkpoints": 0, "needs_cleanup": False},
    }

    with patch(
        "app.api.projects.pulse.build_project_pulse",
        new=AsyncMock(return_value=payload),
    ) as mock_build:
        response = client.get("/api/projects/agent-hub/pulse")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == "agent-hub"
    assert body["summary"]["active_sessions"] == 2
    assert body["summary"]["stale_sessions"] == 1
    assert body["running_tasks"][0]["id"] == "task-1"
    mock_build.assert_awaited_once_with("agent-hub")


def test_get_project_pulse_compact_omits_large_session_rows(client) -> None:
    payload = {
        "project_id": "agent-hub",
        "generated_at": "2026-03-08T00:00:00Z",
        "summary": {"active_sessions": 100},
        "cleanup": {"needs_cleanup": False},
        "active_sessions": [{"id": f"sess-{idx}", "live_activity": {"large": "x" * 1000}} for idx in range(20)],
        "active_owners": [{"session_id": "sess-1", "scope_paths": ["backend"]}],
    }

    with patch(
        "app.api.projects.pulse.build_project_pulse",
        new=AsyncMock(return_value=payload),
    ):
        response = client.get("/api/projects/agent-hub/pulse?compact=true")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "project_id": "agent-hub",
        "generated_at": "2026-03-08T00:00:00Z",
        "summary": {"active_sessions": 100},
        "cleanup": {"needs_cleanup": False},
    }
