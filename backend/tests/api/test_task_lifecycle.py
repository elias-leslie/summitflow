"""API tests for task execution lifecycle endpoints."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock


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
            json={
                "title": "Execution target",
                "task_type": "bug",
                "priority": 2,
                "complexity": "SIMPLE",
                "objective": "Restore healthy response",
                "done_when": ["GET /health returns 200", "Relevant tests pass"],
            },
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        mocker.patch(
            "app.api.tasks.update_endpoints.validate_task_ready",
            return_value=SimpleNamespace(ready=True, issues=[], suggestions=[], lane_conflict=None),
        )
        mock_dispatch = mocker.patch(
            "app.api.tasks.update_endpoints.dispatch_task",
            new_callable=AsyncMock,
            return_value={
                "task_id": task_id,
                "project_id": test_project_id,
                "stage": "execution",
                "status": "dispatched",
            },
        )

        response = client.post(f"/api/projects/{test_project_id}/tasks/{task_id}/execute")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == task_id
        assert data["status"] == "pending"
        mock_dispatch.assert_awaited_once_with(task_id, test_project_id)

    def test_execute_surfaces_dispatch_failure(
        self,
        client: Any,
        test_project_id: str,
        cleanup_task: Callable[[str], None],
        mocker: Any,
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Execution guard target",
                "task_type": "bug",
                "priority": 2,
                "complexity": "SIMPLE",
                "objective": "Verify dispatch errors reach the UI",
                "done_when": ["Start Execution shows a clear error"],
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        mocker.patch(
            "app.api.tasks.update_endpoints.validate_task_ready",
            return_value=SimpleNamespace(ready=True, issues=[], suggestions=[], lane_conflict=None),
        )
        mocker.patch(
            "app.api.tasks.update_endpoints.dispatch_task",
            new_callable=AsyncMock,
            return_value={
                "task_id": task_id,
                "project_id": test_project_id,
                "stage": "blocked",
                "status": "disabled",
                "reason": "not_allowed",
            },
        )

        response = client.post(f"/api/projects/{test_project_id}/tasks/{task_id}/execute")

        assert response.status_code == 503
        body = response.json()
        assert body["message"] == "Failed to start autonomous execution"
        assert body["dispatch"]["status"] == "disabled"
        assert body["dispatch"]["reason"] == "not_allowed"

    def test_execute_rejects_manual_only_task(
        self,
        client: Any,
        test_project_id: str,
        cleanup_task: Callable[[str], None],
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Manual-only target",
                "task_type": "task",
                "priority": 2,
                "execution_mode": "manual_only",
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        response = client.post(f"/api/projects/{test_project_id}/tasks/{task_id}/execute")

        assert response.status_code == 400
        assert "manual" in response.json()["message"].lower()

    def test_execute_rejects_task_missing_execution_details(
        self,
        client: Any,
        test_project_id: str,
        cleanup_task: Callable[[str], None],
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={"title": "Draft execution target", "task_type": "feature", "priority": 2},
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        response = client.post(f"/api/projects/{test_project_id}/tasks/{task_id}/execute")

        assert response.status_code == 422
        body = response.json()
        body_text = str(body)
        assert "description" in body_text or "done_when" in body_text

    def test_execute_rejects_lane_overlap_from_validation(
        self,
        client: Any,
        test_project_id: str,
        cleanup_task: Callable[[str], None],
        mocker: Any,
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Lane overlap execution target",
                "task_type": "task",
                "priority": 1,
                "complexity": "STANDARD",
                "objective": "Queue only when no exact file overlap exists.",
                "spirit_anti": "Do not run when another active lane owns the same file.",
                "done_when": ["Execution is blocked when overlap exists"],
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        mocker.patch(
            "app.api.tasks.update_endpoints.validate_task_ready",
            return_value=SimpleNamespace(
                ready=False,
                issues=["Another active coding session overlaps exact files in project summitflow: task-999 (backend/app/foo.py)"],
                suggestions=["Exact-file overlap with task-999: backend/app/foo.py. Finish or retire the active session before dispatching another coding task."],
                lane_conflict={
                    "overlap_kind": "exact_file",
                    "disposition": "block",
                    "overlap_paths": ["backend/app/foo.py"],
                    "shared_plumbing": False,
                    "conflicting_tasks": ["task-999"],
                },
            ),
        )

        response = client.post(f"/api/projects/{test_project_id}/tasks/{task_id}/execute")

        assert response.status_code == 422
        body = response.json()
        body_text = str(body)
        assert "execution-ready" in body_text or "HTTP Error" in body_text
        assert "overlaps exact files" in body_text
        # Custom error handler wraps detail in details[] array
        details_list = body.get("details", [body.get("detail", body)])
        lane_info = details_list[0]["lane_conflict"]
        assert lane_info["overlap_kind"] == "exact_file"
        assert lane_info["disposition"] == "block"
        assert "backend/app/foo.py" in lane_info["overlap_paths"]

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

    def test_global_review_uses_task_project_id(
        self,
        client: Any,
        mocker: Any,
    ) -> None:
        task = {"id": "task-1", "project_id": "agent-hub", "title": "Review target"}
        mocker.patch("app.api.tasks.get_endpoints.get_task_or_404", return_value=task)
        mocker.patch(
            "app.tasks.autonomous.review_modules.diff.get_git_diff",
            return_value="diff --git a/test.py b/test.py",
        )
        mocker.patch("app.storage.task_spirit.get_task_spirit", return_value=None)
        mocker.patch(
            "app.tasks.autonomous.review_modules.parsing.parse_review_response",
            return_value={"verdict": "APPROVED", "concerns": [], "summary": "ok"},
        )
        mock_client = MagicMock()
        mock_client.complete.return_value = SimpleNamespace(content='{"verdict":"APPROVED"}')
        mocker.patch("app.services.agent_hub_client.get_sync_client", return_value=mock_client)

        response = client.post("/api/tasks/task-1/review")

        assert response.status_code == 200
        assert response.json()["verdict"] == "APPROVED"
        assert mock_client.complete.call_args.kwargs["project_id"] == "agent-hub"
