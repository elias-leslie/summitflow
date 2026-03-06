"""API tests for task execution lifecycle endpoints."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock


class TestTaskLifecycleEndpoints:
    """Covers validate-ready, execute, claim, and release contracts."""

    def test_validate_ready_returns_service_result(
        self,
        client: Any,
        test_project_id: str,
        cleanup_task: Callable[[str], None],
        mocker: Any,
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={"title": "Validation target", "task_type": "task", "priority": 2},
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        mock_validate = mocker.patch(
            "app.api.tasks.logging.validate_task_ready",
            return_value=SimpleNamespace(
                ready=False,
                issues=["blocked by dependency"],
                suggestions=["resolve blocker first"],
            ),
        )

        response = client.post(f"/api/projects/{test_project_id}/tasks/{task_id}/validate-ready")

        assert response.status_code == 200
        assert response.json() == {
            "ready": False,
            "issues": ["blocked by dependency"],
            "suggestions": ["resolve blocker first"],
        }
        mock_validate.assert_called_once_with(task_id, test_project_id)

    def test_execute_queues_task_and_dispatches(
        self,
        client: Any,
        test_project_id: str,
        cleanup_task: Callable[[str], None],
        mocker: Any,
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={"title": "Execution target", "task_type": "task", "priority": 2},
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        mock_dispatch = mocker.patch(
            "app.api.tasks.update_endpoints.dispatch_autonomous_task",
            new_callable=AsyncMock,
        )

        response = client.post(f"/api/projects/{test_project_id}/tasks/{task_id}/execute")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == task_id
        assert data["status"] == "queue"
        mock_dispatch.assert_awaited_once_with(task_id, "queue", test_project_id)

    def test_claim_and_release_round_trip(
        self,
        client: Any,
        test_project_id: str,
        cleanup_task: Callable[[str], None],
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={"title": "Claim target", "task_type": "task", "priority": 2},
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        claim_response = client.post(
            f"/api/projects/{test_project_id}/tasks/{task_id}/claim",
            json={"worker_id": "worker-1", "lock_minutes": 15},
        )

        assert claim_response.status_code == 200
        claim_data = claim_response.json()
        assert claim_data["id"] == task_id
        assert claim_data["status"] == "running"
        assert claim_data["started_at"] is not None

        release_response = client.post(
            f"/api/projects/{test_project_id}/tasks/{task_id}/release",
        )

        assert release_response.status_code == 200
        release_data = release_response.json()
        assert release_data["id"] == task_id
        assert release_data["status"] == "pending"

    def test_release_rejects_unclaimed_task(
        self,
        client: Any,
        test_project_id: str,
        cleanup_task: Callable[[str], None],
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={"title": "Unclaimed target", "task_type": "task", "priority": 2},
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        release_response = client.post(
            f"/api/projects/{test_project_id}/tasks/{task_id}/release",
        )

        assert release_response.status_code == 400
        body = release_response.json()
        assert "not currently claimed" in body["message"]
