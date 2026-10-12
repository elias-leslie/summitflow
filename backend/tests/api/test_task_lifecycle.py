"""API tests for task execution lifecycle endpoints."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any


class TestTaskLifecycleEndpoints:
    """Covers validate-ready, claim, and release contracts."""

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

        renewed_response = client.post(
            f"/api/projects/{test_project_id}/tasks/{task_id}/claim",
            json={"worker_id": "worker-1", "lock_minutes": 30, "renew_only": True},
        )
        assert renewed_response.status_code == 200
        renewed = renewed_response.json()
        assert renewed["started_at"] == claim_data["started_at"]
        assert renewed["lock_expires_at"] > claim_data["lock_expires_at"]

        wrong_owner_response = client.post(
            f"/api/projects/{test_project_id}/tasks/{task_id}/claim",
            json={"worker_id": "worker-2", "lock_minutes": 30, "renew_only": True},
        )
        assert wrong_owner_response.status_code == 409

        release_response = client.post(
            f"/api/projects/{test_project_id}/tasks/{task_id}/release",
        )

        assert release_response.status_code == 200
        release_data = release_response.json()
        assert release_data["id"] == task_id
        assert release_data["status"] == "pending"

        pending_renewal = client.post(
            f"/api/projects/{test_project_id}/tasks/{task_id}/claim",
            json={"worker_id": "worker-1", "lock_minutes": 30, "renew_only": True},
        )
        assert pending_renewal.status_code == 409

    def test_claim_accepts_short_task_suffix(
        self,
        client: Any,
        test_project_id: str,
        cleanup_task: Callable[[str], None],
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={"title": "Short claim target", "task_type": "task", "priority": 2},
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        short_id = task_id.removeprefix("task-")
        claim_response = client.post(
            f"/api/projects/{test_project_id}/tasks/{short_id}/claim",
            json={"worker_id": "worker-1", "lock_minutes": 15},
        )

        assert claim_response.status_code == 200
        assert claim_response.json()["id"] == task_id

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
