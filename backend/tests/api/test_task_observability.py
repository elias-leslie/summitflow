"""Tests for task Agent Hub observability endpoints."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch


class TestTaskObservability:
    """Project scoping and event aggregation regressions."""

    def test_get_agent_events_wrong_project_returns_404(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        """Observability routes must respect the task's owning project."""
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={"title": "Observed task", "task_type": "task"},
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        response = client.get(f"/api/projects/wrong-project/tasks/{task_id}/agent-events")
        assert response.status_code == 404

        response = client.get(f"/api/projects/wrong-project/tasks/{task_id}/agent-sessions")
        assert response.status_code == 404

    def test_get_agent_events_owning_project_returns_sessions(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        """Linked Agent Hub sessions should be returned only for the owning project."""
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={"title": "Observed task", "task_type": "task"},
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        with patch(
            "app.api.tasks.observability.get_agent_hub_sessions",
            return_value=["sess-1"],
        ), patch(
            "app.api.tasks.observability._fetch_session_summary",
            return_value={
                "id": "sess-1",
                "status": "active",
                "effective_model": "claude-sonnet-4-6",
                "updated_at": "2026-03-07T00:00:00Z",
                "live_activity": {
                    "phase": "reading_file",
                    "status": "active",
                    "summary": "Reading file",
                    "health": "active",
                    "stalled": False,
                    "files_touched": [],
                    "outstanding_tool_calls": 1,
                    "tool_calls_count": 1,
                },
            },
        ), patch(
            "app.api.tasks.observability._fetch_session_events",
            return_value={
                "events": [
                    {
                        "id": "evt-1",
                        "turn": 1,
                        "sequence": 1,
                        "event_type": "assistant_message",
                        "content": "done",
                        "created_at": "2026-03-07T00:00:00Z",
                    }
                ],
                "total": 1,
                "max_turn": 1,
            },
        ):
            response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/agent-events")

        assert response.status_code == 200
        body = response.json()
        assert body["session_ids"] == ["sess-1"]
        assert body["sessions"][0]["id"] == "sess-1"
        assert body["sessions"][0]["live_activity"]["phase"] == "reading_file"
        assert body["total"] == 1
        assert body["events"][0]["id"] == "evt-1"
