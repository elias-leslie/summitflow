"""Tests for task Agent Hub observability endpoints."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch


class TestTaskObservability:
    """Project scoping and event aggregation regressions."""

    def test_agent_events_requires_correct_project(
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

    def test_agent_events_returns_linked_sessions_for_task_project(
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
        assert body["total"] == 1
        assert body["events"][0]["id"] == "evt-1"
