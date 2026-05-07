"""Tests for task Agent Hub observability endpoints."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from app.api.tasks.observability import _infer_session_task_id


class TestTaskObservability:
    """Project scoping and event aggregation regressions."""

    def test_infer_session_task_id_uses_repo_root_path(self) -> None:
        assert _infer_session_task_id(
            {
                "external_id": None,
                "current_branch": None,
                "repo_root": "/srv/workspaces/projects/agent-hub/task-bc3ed9c0",
            }
        ) == "task-bc3ed9c0"

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
                "effective_model": "served-model",
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

    def test_get_agent_events_falls_back_to_external_id_sessions_and_backfills(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        """Fallback to Agent Hub sessions by external_id when stored links are missing."""
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={"title": "Observed task", "task_type": "task"},
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        discovered_session = {
            "id": "sess-fallback",
            "status": "completed",
            "external_id": task_id,
            "effective_model": "served-code-model",
            "updated_at": "2026-03-26T00:00:00Z",
            "live_activity": {
                "phase": "completed",
                "status": "completed",
                "summary": "Execution completed",
                "health": "completed",
                "stalled": False,
                "files_touched": [],
                "outstanding_tool_calls": 0,
                "tool_calls_count": 2,
            },
        }

        with patch(
            "app.api.tasks.observability.get_agent_hub_sessions",
            return_value=[],
        ), patch(
            "app.api.tasks.observability._fetch_task_sessions_by_external_id",
            return_value=[discovered_session],
        ), patch(
            "app.api.tasks.observability.add_agent_hub_session",
        ) as mock_add_session, patch(
            "app.api.tasks.observability._fetch_session_events",
            return_value={
                "events": [
                    {
                        "id": "evt-fallback",
                        "turn": 1,
                        "sequence": 1,
                        "event_type": "assistant_message",
                        "content": "done",
                        "created_at": "2026-03-26T00:00:00Z",
                    }
                ],
                "total": 1,
                "max_turn": 1,
            },
        ):
            response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/agent-events")

        assert response.status_code == 200
        body = response.json()
        assert body["session_ids"] == ["sess-fallback"]
        assert body["sessions"][0]["id"] == "sess-fallback"
        assert body["events"][0]["id"] == "evt-fallback"
        mock_add_session.assert_called_once_with(task_id, "sess-fallback")

    def test_get_agent_events_falls_back_to_repo_root_linked_sessions_and_backfills(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        """Fallback should also recover task-linked sessions from checkout metadata."""
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={"title": "Observed task", "task_type": "task"},
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        discovered_session = {
            "id": "sess-repo-root",
            "status": "active",
            "external_id": None,
            "current_branch": None,
            "repo_root": f"/srv/workspaces/projects/{test_project_id}/{task_id}",
            "effective_model": "served-model",
            "updated_at": "2026-03-26T00:00:00Z",
            "live_activity": {
                "phase": "finalizing",
                "status": "active",
                "summary": "Finalizing checkout",
                "health": "stalled",
                "stalled": True,
                "files_touched": [],
                "outstanding_tool_calls": 0,
                "tool_calls_count": 2,
            },
        }

        with patch(
            "app.api.tasks.observability.get_agent_hub_sessions",
            return_value=[],
        ), patch(
            "app.api.tasks.observability._fetch_task_sessions_by_external_id",
            return_value=[discovered_session],
        ), patch(
            "app.api.tasks.observability.add_agent_hub_session",
        ) as mock_add_session, patch(
            "app.api.tasks.observability._fetch_session_events",
            return_value={
                "events": [
                    {
                        "id": "evt-repo-root",
                        "turn": 1,
                        "sequence": 1,
                        "event_type": "assistant_message",
                        "content": "done",
                        "created_at": "2026-03-26T00:00:00Z",
                    }
                ],
                "total": 1,
                "max_turn": 1,
            },
        ):
            response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/agent-events")

        assert response.status_code == 200
        body = response.json()
        assert body["session_ids"] == ["sess-repo-root"]
        assert body["sessions"][0]["id"] == "sess-repo-root"
        assert body["events"][0]["id"] == "evt-repo-root"
        mock_add_session.assert_called_once_with(task_id, "sess-repo-root")
