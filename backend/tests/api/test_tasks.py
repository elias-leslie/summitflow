"""Integration tests for task_spirit JOIN in tasks API.

Tests verify that:
1. Task with spirit data returns done_when, plan_status, complexity, context
2. Task without spirit data returns null/empty for spirit fields
3. List endpoint returns spirit fields for all tasks
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from app.storage import tasks as task_store
from app.storage.connection import get_connection
from app.storage.task_spirit import get_task_spirit


class TestTaskSpiritJoin:
    """Test task_spirit LEFT JOIN functionality."""

    def test_get_task_with_spirit_data(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        """Task with spirit data should return done_when and plan_status populated."""
        # Create a task
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task with spirit data",
                "description": "Testing spirit JOIN",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        # Add spirit data directly to database
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_spirit (task_id, done_when, plan_status)
                VALUES (%s, %s::jsonb, %s)
                """,
                (
                    task_id,
                    json.dumps(["All tests pass", "PR merged"]),
                    "approved",
                ),
            )
            conn.commit()

        # Fetch task and verify spirit fields
        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}")
        assert response.status_code == 200
        task_data = response.json()

        assert task_data["done_when"] == ["All tests pass", "PR merged"]
        assert task_data["plan_status"] == "approved"

    def test_get_task_without_spirit_data(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        """Task without spirit data should return null/empty for spirit fields."""
        # Create a task (no spirit data)
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task without spirit data",
                "description": "Testing graceful null handling",
                "task_type": "bug",
                "priority": 1,
            },
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        # Fetch task and verify spirit fields are null/empty
        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}")
        assert response.status_code == 200
        task_data = response.json()

        # Spirit fields should be null or empty lists (graceful handling)
        assert task_data["done_when"] == [] or task_data["done_when"] is None

    def test_list_tasks_returns_spirit_fields(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        """List endpoint should return tasks with spirit fields populated."""
        # Create two tasks - one with spirit, one without
        response1 = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Task with spirit for list test",
                "task_type": "feature",
            },
        )
        assert response1.status_code == 200
        task1_id = response1.json()["id"]
        cleanup_task(task1_id)

        response2 = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Task without spirit for list test",
                "task_type": "task",
            },
        )
        assert response2.status_code == 200
        task2_id = response2.json()["id"]
        cleanup_task(task2_id)

        # Add spirit data to first task
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_spirit (task_id, plan_status)
                VALUES (%s, %s)
                """,
                (task1_id, "draft"),
            )
            conn.commit()

        # List tasks and find our test tasks
        response = client.get(f"/api/projects/{test_project_id}/tasks?limit=500")
        assert response.status_code == 200
        tasks = response.json()["tasks"]

        # Find our test tasks
        task1_data = next((t for t in tasks if t["id"] == task1_id), None)
        task2_data = next((t for t in tasks if t["id"] == task2_id), None)

        assert task1_data is not None, "Task with spirit not found in list"
        assert task2_data is not None, "Task without spirit not found in list"

        # Verify spirit fields on task with spirit
        assert task1_data["plan_status"] == "draft"


class TestTaskUpdates:
    """Regression tests for task update behavior."""

    def test_task_update_labels_persists(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        """Labels should update through the project task PATCH endpoint."""
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Task with labels",
                "task_type": "task",
                "labels": ["initial"],
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        response = client.patch(
            f"/api/projects/{test_project_id}/tasks/{task_id}",
            json={"labels": ["updated", "autonomous"]},
        )
        assert response.status_code == 200

        updated = response.json()
        assert updated["labels"] == ["updated", "autonomous"]

        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}")
        assert response.status_code == 200
        assert response.json()["labels"] == ["updated", "autonomous"]

    def test_task_update_execution_mode_persists(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Task with execution mode",
                "task_type": "task",
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        response = client.patch(
            f"/api/projects/{test_project_id}/tasks/{task_id}",
            json={"execution_mode": "manual"},
        )
        assert response.status_code == 200
        updated = response.json()
        assert updated["execution_mode"] == "manual"

    def test_task_update_plan_context_persists(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Task with plan context",
                "task_type": "task",
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        response = client.patch(
            f"/api/projects/{test_project_id}/tasks/{task_id}",
            json={
                "objective": "Restore rich plan fidelity",
                "constraints": ["Keep updates lean"],
                "decisions": [{"id": "d1", "title": "Reuse context blob", "outcome": "accepted"}],
                "done_when": ["Task context shows planner fields"],
            },
        )
        assert response.status_code == 200

        spirit = get_task_spirit(task_id)
        assert spirit is not None
        assert spirit["done_when"] == ["Task context shows planner fields"]
        assert spirit["objective"] == "Restore rich plan fidelity"
        assert spirit["constraints"] == ["Keep updates lean"]
        assert spirit["decisions"] == [
            {"id": "d1", "title": "Reuse context blob", "outcome": "accepted"}
        ]


class TestShortTaskIdApiResolution:
    def test_get_task_accepts_short_suffix(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={"title": "Short id API target", "task_type": "task"},
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        short_id = task_id.removeprefix("task-")
        response = client.get(f"/api/tasks/{short_id}")

        assert response.status_code == 200
        assert response.json()["id"] == task_id

    def test_completion_readiness_ignores_synthetic_no_step_subtasks(self, client: Any) -> None:
        task_id = f"task-{uuid4()}"
        task = {
            "id": task_id,
            "syncable_subtasks_skipped": ["1.1:no-steps", "1.2:no-steps", "1.3:no-steps"],
        }
        subtasks = [
            {"subtask_id": "1.1", "passes": False, "steps": []},
            {"subtask_id": "1.2", "passes": False, "steps": []},
            {"subtask_id": "1.3", "passes": False, "steps": []},
        ]

        with (
            patch("app.api.tasks.get_endpoints.get_task_or_404", return_value=task),
            patch("app.api.tasks.get_endpoints.get_subtasks_for_task", return_value=subtasks),
        ):
            result = client.get(f"/api/tasks/{task_id}/completion-readiness")

        assert result.status_code == 200
        assert result.json() == {"ready": True, "gates": []}

    def test_completion_readiness_ignores_synthetic_zero_step_summary_subtasks(self, client: Any) -> None:
        task_id = f"task-{uuid4()}"
        task = {
            "id": task_id,
            "syncable_subtasks_skipped": ["1.1:no-steps"],
        }
        subtasks = [
            {
                "subtask_id": "1.1",
                "passes": False,
                "steps": [],
                "steps_from_table": [],
                "step_summary": {"completed": 0, "total": 0},
            },
        ]

        with (
            patch("app.api.tasks.get_endpoints.get_task_or_404", return_value=task),
            patch("app.api.tasks.get_endpoints.get_subtasks_for_task", return_value=subtasks),
        ):
            result = client.get(f"/api/tasks/{task_id}/completion-readiness")

        assert result.status_code == 200
        assert result.json() == {"ready": True, "gates": []}

    def test_completion_readiness_keeps_real_incomplete_subtasks_blocking(self, client: Any) -> None:
        task_id = f"task-{uuid4()}"
        task = {
            "id": task_id,
            "syncable_subtasks_skipped": ["1.1:no-steps"],
        }
        subtasks = [
            {"subtask_id": "1.1", "passes": False, "steps": []},
            {"subtask_id": "1.2", "passes": False, "steps": [{"step_number": 1, "passes": False}]},
        ]

        with (
            patch("app.api.tasks.get_endpoints.get_task_or_404", return_value=task),
            patch("app.api.tasks.get_endpoints.get_subtasks_for_task", return_value=subtasks),
        ):
            result = client.get(f"/api/tasks/{task_id}/completion-readiness")

        assert result.status_code == 200
        assert result.json() == {
            "ready": False,
            "gates": [{"gate": "subtasks", "pass": False, "detail": ["1.2"]}],
        }

    def test_completion_readiness_accepts_short_suffix(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={"title": "Short id readiness target", "task_type": "task"},
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        short_id = task_id.removeprefix("task-")
        response = client.get(f"/api/tasks/{short_id}/completion-readiness")

        assert response.status_code == 200
        assert response.json()["ready"]

    def test_create_simple_task_auto_approves_when_execution_ready(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Ready bug task",
                "description": "Fix failing health endpoint",
                "task_type": "bug",
                "complexity": "SIMPLE",
                "objective": "Restore 200 on /health",
                "done_when": ["GET /health returns 200", "Relevant tests pass"],
            },
        )
        assert response.status_code == 200
        task = response.json()
        cleanup_task(task["id"])

        assert task["plan_status"] == "approved"


class TestReadyEndpoint:
    """Execution-ready filtering for /tasks/ready."""

    def test_ready_endpoint_excludes_tasks_with_live_lane(
        self, client: Any, test_project_id: str
    ) -> None:
        ready_task = {
            "id": "task-ready",
            "project_id": test_project_id,
            "capability_id": None,
            "title": "Idle ready task",
            "description": "Ready to execute",
            "status": "pending",
            "error_message": None,
            "branch_name": None,
            "commits": [],
            "total_sessions": 0,
            "total_tokens_used": 0,
            "created_at": None,
            "started_at": None,
            "completed_at": None,
            "priority": 1,
            "labels": [],
            "task_type": "bug",
            "parent_task_id": None,
            "current_phase": None,
            "verification_result": None,
            "done_when": ["GET /health returns 200"],
            "complexity": "SIMPLE",
            "raw_request": None,
            "enrichment_status": "none",
            "enriched_by": None,
            "enriched_at": None,
            "subtask_summary": {"total": 0, "completed": 0, "progress_percent": 0.0},
            "execution_mode": "autonomous",
            "autonomous": True,
            "ai_review": True,
            "agent_override": None,
            "plan_status": "approved",
            "plan_approved_at": None,
            "plan_approved_by": None,
            "context": None,
        }
        ready_live_task = {
            **ready_task,
            "id": "task-ready-live",
            "title": "Already executing ready task",
        }

        def _fake_sync(task_id: str):
            class _Readiness:
                def __init__(self, ready: bool):
                    self.ready = ready

            return _Readiness(task_id in {"task-ready", "task-ready-live"})

        with (
            patch(
                "app.api.tasks.list_endpoints.task_store.list_ready_tasks",
                return_value=[ready_task, ready_live_task],
            ),
            patch(
                "app.services.task_execution_readiness.sync_task_execution_readiness",
                side_effect=_fake_sync,
            ),
            patch(
                "app.api.tasks.list_endpoints.fetch_live_project_inventory",
                return_value=(
                    [
                        {
                            "external_id": "task-ready-live",
                            "current_branch": "task-ready-live/main",
                        }
                    ],
                    [{"task_id": "task-ready-live"}],
                ),
            ),
        ):
            response = client.get(f"/api/projects/{test_project_id}/tasks/ready?limit=20")

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert [task["id"] for task in payload["tasks"]] == ["task-ready"]

    def test_ready_endpoint_excludes_tasks_with_checkpoint(
        self, client: Any, test_project_id: str
    ) -> None:
        ready_task = {
            "id": "task-ready",
            "project_id": test_project_id,
            "capability_id": None,
            "title": "Idle ready task",
            "description": "Ready to execute",
            "status": "pending",
            "error_message": None,
            "branch_name": None,
            "commits": [],
            "total_sessions": 0,
            "total_tokens_used": 0,
            "created_at": None,
            "started_at": None,
            "completed_at": None,
            "priority": 1,
            "labels": [],
            "task_type": "bug",
            "parent_task_id": None,
            "current_phase": None,
            "verification_result": None,
            "done_when": ["GET /health returns 200"],
            "complexity": "SIMPLE",
            "raw_request": None,
            "enrichment_status": "none",
            "enriched_by": None,
            "enriched_at": None,
            "subtask_summary": {"total": 0, "completed": 0, "progress_percent": 0.0},
            "execution_mode": "autonomous",
            "autonomous": True,
            "ai_review": True,
            "agent_override": None,
            "plan_status": "approved",
            "plan_approved_at": None,
            "plan_approved_by": None,
            "context": None,
        }
        ready_checkpoint_task = {
            **ready_task,
            "id": "task-ready-checkpoint",
            "title": "Ready but already has checkpoint",
        }

        def _fake_sync(task_id: str):
            class _Readiness:
                def __init__(self, ready: bool):
                    self.ready = ready

            return _Readiness(task_id in {"task-ready", "task-ready-checkpoint"})

        with (
            patch(
                "app.api.tasks.list_endpoints.task_store.list_ready_tasks",
                return_value=[ready_task, ready_checkpoint_task],
            ),
            patch(
                "app.services.task_execution_readiness.sync_task_execution_readiness",
                side_effect=_fake_sync,
            ),
            patch(
                "app.api.tasks.list_endpoints.has_active_checkpoint",
                side_effect=lambda task_id, project_id=None: (
                    task_id == "task-ready-checkpoint" and project_id == test_project_id
                ),
            ),
        ):
            response = client.get(f"/api/projects/{test_project_id}/tasks/ready?limit=20")

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert [task["id"] for task in payload["tasks"]] == ["task-ready"]

    def test_ready_endpoint_degrades_when_live_lane_inventory_fails(
        self, client: Any, test_project_id: str
    ) -> None:
        ready_task = {
            "id": "task-ready",
            "project_id": test_project_id,
            "capability_id": None,
            "title": "Idle ready task",
            "description": "Ready to execute",
            "status": "pending",
            "error_message": None,
            "branch_name": None,
            "commits": [],
            "total_sessions": 0,
            "total_tokens_used": 0,
            "created_at": None,
            "started_at": None,
            "completed_at": None,
            "priority": 1,
            "labels": [],
            "task_type": "bug",
            "parent_task_id": None,
            "current_phase": None,
            "verification_result": None,
            "done_when": ["Relevant tests pass"],
            "complexity": "SIMPLE",
            "raw_request": None,
            "enrichment_status": "none",
            "enriched_by": None,
            "enriched_at": None,
            "subtask_summary": {"total": 0, "completed": 0, "progress_percent": 0.0},
            "execution_mode": "manual",
            "autonomous": False,
            "ai_review": True,
            "agent_override": None,
            "plan_status": "approved",
            "plan_approved_at": None,
            "plan_approved_by": None,
            "context": None,
        }

        def _fake_sync(task_id: str):
            class _Readiness:
                def __init__(self, ready: bool):
                    self.ready = ready

            return _Readiness(task_id == "task-ready")

        with (
            patch(
                "app.api.tasks.list_endpoints.task_store.list_ready_tasks",
                return_value=[ready_task],
            ),
            patch(
                "app.services.task_execution_readiness.sync_task_execution_readiness",
                side_effect=_fake_sync,
            ),
            patch(
                "app.api.tasks.list_endpoints.fetch_live_project_inventory",
                side_effect=RuntimeError("agent hub unavailable"),
            ),
        ):
            response = client.get(f"/api/projects/{test_project_id}/tasks/ready?limit=20")

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert [task["id"] for task in payload["tasks"]] == ["task-ready"]

    def test_ready_endpoint_keeps_pickup_tasks_without_plan_theatre(
        self, client: Any, test_project_id: str
    ) -> None:
        draft_task = {
            "id": "task-draft",
            "project_id": test_project_id,
            "capability_id": None,
            "title": "Draft refactor task",
            "description": "Needs planning before execution",
            "status": "pending",
            "error_message": None,
            "branch_name": None,
            "commits": [],
            "total_sessions": 0,
            "total_tokens_used": 0,
            "created_at": None,
            "started_at": None,
            "completed_at": None,
            "priority": 2,
            "labels": [],
            "task_type": "refactor",
            "parent_task_id": None,
            "current_phase": None,
            "verification_result": None,
            "done_when": [],
            "complexity": "STANDARD",
            "raw_request": None,
            "enrichment_status": "none",
            "enriched_by": None,
            "enriched_at": None,
            "subtask_summary": {"total": 0, "completed": 0, "progress_percent": 0.0},
            "execution_mode": "manual",
            "autonomous": False,
            "ai_review": True,
            "agent_override": None,
            "plan_status": "draft",
            "plan_approved_at": None,
            "plan_approved_by": None,
            "context": None,
        }
        ready_task = {
            **draft_task,
            "id": "task-ready",
            "title": "Ready bug task",
            "task_type": "bug",
            "priority": 1,
            "done_when": ["GET /health returns 200", "Relevant tests pass"],
            "complexity": "SIMPLE",
            "plan_status": "approved",
        }

        with patch(
            "app.api.tasks.list_endpoints.task_store.list_ready_tasks",
            return_value=[draft_task, ready_task],
        ):
            response = client.get(f"/api/projects/{test_project_id}/tasks/ready?limit=20")

        assert response.status_code == 200
        tasks = response.json()["tasks"]
        task_ids = {task["id"] for task in tasks}

        assert "task-ready" in task_ids
        assert "task-draft" in task_ids

    def test_ready_endpoint_scans_beyond_small_limit_candidate_window(
        self, client: Any, test_project_id: str
    ) -> None:
        template = {
            "project_id": test_project_id,
            "capability_id": None,
            "description": "Generated refactor task",
            "status": "pending",
            "error_message": None,
            "branch_name": None,
            "commits": [],
            "total_sessions": 0,
            "total_tokens_used": 0,
            "created_at": None,
            "started_at": None,
            "completed_at": None,
            "priority": 2,
            "labels": [],
            "task_type": "refactor",
            "parent_task_id": None,
            "current_phase": None,
            "verification_result": None,
            "done_when": ["Tests pass"],
            "complexity": "STANDARD",
            "raw_request": None,
            "enrichment_status": "none",
            "enriched_by": None,
            "enriched_at": None,
            "subtask_summary": {"total": 0, "completed": 0, "progress_percent": 0.0},
            "execution_mode": "autonomous",
            "autonomous": True,
            "ai_review": True,
            "agent_override": None,
            "plan_status": "approved",
            "plan_approved_at": None,
            "plan_approved_by": None,
            "context": None,
        }
        first_batch = [
            {
                **template,
                "id": f"task-unready-{idx}",
                "title": f"Unready task {idx}",
            }
            for idx in range(25)
        ]
        second_batch = [
            {
                **template,
                "id": f"task-ready-{idx}",
                "title": f"Ready task {idx}",
                "priority": 1,
            }
            for idx in range(4)
        ]

        def _fake_list_ready_tasks(project_id: str, limit: int = 50, offset: int = 0):
            assert project_id == test_project_id
            assert limit == 30
            if offset == 0:
                return first_batch + second_batch[:5]
            return []

        with patch(
            "app.api.tasks.list_endpoints.task_store.list_ready_tasks",
            side_effect=_fake_list_ready_tasks,
        ):
            response = client.get(f"/api/projects/{test_project_id}/tasks/ready?limit=3")

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 29
        assert [task["id"] for task in payload["tasks"]] == [
            "task-ready-0",
            "task-ready-1",
            "task-ready-2",
        ]

    def test_ready_endpoint_orders_smaller_work_before_complex_features(
        self, client: Any, test_project_id: str
    ) -> None:
        template = {
            "project_id": test_project_id,
            "capability_id": None,
            "description": "Ready task",
            "status": "pending",
            "error_message": None,
            "branch_name": None,
            "commits": [],
            "total_sessions": 0,
            "total_tokens_used": 0,
            "created_at": None,
            "started_at": None,
            "completed_at": None,
            "labels": [],
            "parent_task_id": None,
            "current_phase": None,
            "verification_result": None,
            "done_when": ["Relevant checks pass"],
            "raw_request": None,
            "enrichment_status": "none",
            "enriched_by": None,
            "enriched_at": None,
            "subtask_summary": {"total": 0, "completed": 0, "progress_percent": 0.0},
            "execution_mode": "autonomous",
            "autonomous": True,
            "ai_review": True,
            "agent_override": None,
            "plan_status": "approved",
            "plan_approved_at": None,
            "plan_approved_by": None,
            "context": None,
        }
        tasks = [
            {
                **template,
                "id": "task-complex-feature",
                "title": "Complex feature",
                "priority": 1,
                "task_type": "feature",
                "complexity": "COMPLEX",
            },
            {
                **template,
                "id": "task-simple-refactor",
                "title": "Simple refactor",
                "priority": 2,
                "task_type": "refactor",
                "complexity": "SIMPLE",
            },
        ]

        def _fake_sync(task_id: str):
            class _Readiness:
                ready = True

            return _Readiness()

        with (
            patch(
                "app.api.tasks.list_endpoints.task_store.list_ready_tasks",
                return_value=tasks,
            ),
            patch(
                "app.services.task_execution_readiness.sync_task_execution_readiness",
                side_effect=_fake_sync,
            ),
        ):
            response = client.get(f"/api/projects/{test_project_id}/tasks/ready?limit=2")

        assert response.status_code == 200
        assert [task["id"] for task in response.json()["tasks"]] == [
            "task-simple-refactor",
            "task-complex-feature",
        ]

    def test_ready_endpoint_promotes_tasks_that_unblock_other_work(
        self, client: Any, test_project_id: str
    ) -> None:
        template = {
            "project_id": test_project_id,
            "capability_id": None,
            "description": "Ready task",
            "status": "pending",
            "error_message": None,
            "branch_name": None,
            "commits": [],
            "total_sessions": 0,
            "total_tokens_used": 0,
            "created_at": None,
            "started_at": None,
            "completed_at": None,
            "labels": [],
            "parent_task_id": None,
            "current_phase": None,
            "verification_result": None,
            "done_when": ["Relevant checks pass"],
            "raw_request": None,
            "enrichment_status": "none",
            "enriched_by": None,
            "enriched_at": None,
            "subtask_summary": {"total": 0, "completed": 0, "progress_percent": 0.0},
            "execution_mode": "autonomous",
            "autonomous": True,
            "ai_review": True,
            "agent_override": None,
            "plan_status": "approved",
            "plan_approved_at": None,
            "plan_approved_by": None,
            "context": None,
        }
        tasks = [
            {
                **template,
                "id": "task-simple-unrelated",
                "title": "Simple unrelated bug",
                "priority": 2,
                "task_type": "bug",
                "complexity": "SIMPLE",
            },
            {
                **template,
                "id": "task-baseline-blocker",
                "title": "Baseline blocker",
                "priority": 1,
                "task_type": "bug",
                "complexity": "STANDARD",
            },
        ]

        class _Readiness:
            ready = True

        with (
            patch(
                "app.api.tasks.list_endpoints.task_store.list_ready_tasks",
                return_value=tasks,
            ),
            patch(
                "app.services.task_execution_readiness.sync_task_execution_readiness",
                return_value=_Readiness(),
            ),
            patch(
                "app.api.tasks.list_endpoints.dep_store.count_blocked_dependents_batch",
                return_value={"task-baseline-blocker": 1},
            ),
        ):
            response = client.get(f"/api/projects/{test_project_id}/tasks/ready?limit=2")

        assert response.status_code == 200
        payload_tasks = response.json()["tasks"]
        assert [task["id"] for task in payload_tasks] == [
            "task-baseline-blocker",
            "task-simple-unrelated",
        ]
        assert payload_tasks[0]["blocking_count"] == 1

    def test_ready_all_overview_returns_payload_and_raw_text(
        self,
        client: Any,
        test_project_id: str,
    ) -> None:
        ready_task = {
            "id": "task-ready",
            "title": "Ready fix",
            "priority": 1,
            "task_type": "bug",
            "execution_mode": "autonomous",
            "status": "pending",
        }
        ready_live_task = {
            "id": "task-ready-live",
            "title": "Ready but already executing",
            "priority": 1,
            "task_type": "task",
            "execution_mode": "autonomous",
            "status": "pending",
        }
        pending_live_task = {
            "id": "task-pending-live",
            "title": "Pending live task",
            "priority": 2,
            "task_type": "task",
            "execution_mode": "manual",
            "status": "pending",
        }
        blocked_task = {
            "id": "task-blocked",
            "title": "Blocked fix",
            "priority": 2,
            "task_type": "task",
            "execution_mode": "manual",
            "status": "pending",
        }
        live_task = {
            "id": "task-live",
            "title": "Live lane task",
            "priority": 1,
            "task_type": "task",
            "execution_mode": "manual",
            "status": "running",
        }
        stale_task = {
            "id": "task-stale",
            "title": "Stale lane task",
            "priority": 2,
            "task_type": "task",
            "execution_mode": "manual",
            "status": "running",
        }

        def _fake_list_tasks(
            project_id: str,
            status_filter: str | None = None,
            limit: int = 50,
            offset: int = 0,
            **_: object,
        ) -> list[dict[str, Any]]:
            assert project_id == test_project_id
            assert limit in {100, 500}
            assert offset == 0
            if status_filter == "pending":
                return [ready_task, ready_live_task, blocked_task, pending_live_task]
            if status_filter == "running":
                return [live_task, stale_task]
            raise AssertionError(f"unexpected status_filter: {status_filter}")

        def _fake_sync(task_id: str):
            class _Readiness:
                def __init__(self, ready: bool):
                    self.ready = ready

            return _Readiness(task_id == "task-ready")

        with (
            patch(
                "app.api.tasks.list_endpoints.project_store.list_projects",
                return_value=[{"id": test_project_id, "name": test_project_id}],
            ),
            patch(
                "app.api.tasks.list_endpoints.task_store.list_ready_tasks",
                return_value=[ready_task],
            ),
            patch(
                "app.services.task_execution_readiness.sync_task_execution_readiness",
                side_effect=_fake_sync,
            ),
            patch(
                "app.api.tasks.list_endpoints.task_store.list_blocked_tasks",
                return_value=[blocked_task],
            ),
            patch(
                "app.api.tasks.list_endpoints.fetch_live_project_inventory",
                return_value=(
                    [
                        {"external_id": "task-live", "current_branch": "task-live/main"},
                        {
                            "external_id": "task-ready-live",
                            "current_branch": "task-ready-live/main",
                        },
                        {
                            "external_id": "task-pending-live",
                            "current_branch": "task-pending-live/main",
                        },
                    ],
                    [
                        {"task_id": "task-live"},
                        {"task_id": "task-ready-live"},
                        {"task_id": "task-pending-live"},
                    ],
                ),
            ),
            patch(
                "app.api.tasks.list_endpoints.task_store.list_tasks",
                side_effect=_fake_list_tasks,
            ),
        ):
            response = client.get("/api/tasks/ready-all?limit=3")

        assert response.status_code == 200
        payload = response.json()
        assert payload["payload"]["summary"] == {
            "ready": 1,
            "blocked": 1,
            "active": 3,
            "stale": 1,
            "projects": 1,
        }
        assert "READY-ALL[1 ready, 1 blocked, 3 active, 1 stale across 1 projects]" in payload["raw"]
        assert "~ task-live" in payload["raw"]
        assert "~ task-ready-live" in payload["raw"]
        assert "~ task-pending-live" in payload["raw"]
        assert "? task-stale" in payload["raw"]
        assert "task-blocked [pending]" not in payload["raw"]

    def test_ready_all_overview_degrades_when_live_lane_inventory_fails(
        self,
        client: Any,
        test_project_id: str,
    ) -> None:
        ready_task = {
            "id": "task-ready",
            "title": "Ready fix",
            "priority": 1,
            "task_type": "bug",
            "execution_mode": "autonomous",
            "status": "pending",
        }

        def _fake_list_tasks(
            project_id: str,
            status_filter: str | None = None,
            limit: int = 50,
            offset: int = 0,
            **_: object,
        ) -> list[dict[str, Any]]:
            assert project_id == test_project_id
            assert limit in {100, 500}
            assert offset == 0
            if status_filter == "pending":
                return [ready_task]
            if status_filter == "running":
                return []
            raise AssertionError(f"unexpected status_filter: {status_filter}")

        with (
            patch(
                "app.api.tasks.list_endpoints.project_store.list_projects",
                return_value=[{"id": test_project_id, "name": test_project_id}],
            ),
            patch(
                "app.api.tasks.list_endpoints.task_store.list_ready_tasks",
                return_value=[ready_task],
            ),
            patch(
                "app.services.task_execution_readiness.sync_task_execution_readiness",
                return_value=type("_Readiness", (), {"ready": True})(),
            ),
            patch(
                "app.api.tasks.list_endpoints.task_store.list_blocked_tasks",
                return_value=[],
            ),
            patch(
                "app.api.tasks.list_endpoints.fetch_live_project_inventory",
                side_effect=RuntimeError("agent hub unavailable"),
            ),
            patch(
                "app.api.tasks.list_endpoints.task_store.list_tasks",
                side_effect=_fake_list_tasks,
            ),
        ):
            response = client.get("/api/tasks/ready-all?limit=3")

        assert response.status_code == 200
        payload = response.json()
        assert payload["payload"]["summary"] == {
            "ready": 1,
            "blocked": 0,
            "active": 0,
            "stale": 0,
            "projects": 1,
        }
        assert "READY-ALL[1 ready, 0 blocked, 0 active, 0 stale across 1 projects]" in payload["raw"]
        assert "* task-ready" in payload["raw"]

    def test_ready_all_overview_treats_checkpoint_backed_tasks_as_active(
        self,
        client: Any,
        test_project_id: str,
    ) -> None:
        ready_checkpoint_task = {
            "id": "task-ready-checkpoint",
            "title": "Ready but already has checkpoint",
            "priority": 1,
            "task_type": "task",
            "execution_mode": "autonomous",
            "status": "pending",
        }
        pending_checkpoint_task = {
            "id": "task-pending-checkpoint",
            "title": "Pending with checkpoint",
            "priority": 2,
            "task_type": "task",
            "execution_mode": "manual",
            "status": "pending",
        }
        running_checkpoint_task = {
            "id": "task-running-checkpoint",
            "title": "Running with checkpoint",
            "priority": 1,
            "task_type": "task",
            "execution_mode": "manual",
            "status": "running",
        }

        def _fake_list_tasks(
            project_id: str,
            status_filter: str | None = None,
            limit: int = 50,
            offset: int = 0,
            **_: object,
        ) -> list[dict[str, Any]]:
            assert project_id == test_project_id
            assert limit in {100, 500}
            assert offset == 0
            if status_filter == "pending":
                return [pending_checkpoint_task]
            if status_filter == "running":
                return [running_checkpoint_task]
            raise AssertionError(f"unexpected status_filter: {status_filter}")

        with (
            patch(
                "app.api.tasks.list_endpoints.project_store.list_projects",
                return_value=[{"id": test_project_id, "name": test_project_id}],
            ),
            patch(
                "app.api.tasks.list_endpoints.task_store.list_ready_tasks",
                return_value=[ready_checkpoint_task],
            ),
            patch(
                "app.services.task_execution_readiness.sync_task_execution_readiness",
                return_value=type("_Readiness", (), {"ready": True})(),
            ),
            patch(
                "app.api.tasks.list_endpoints.task_store.list_blocked_tasks",
                return_value=[],
            ),
            patch(
                "app.api.tasks.list_endpoints.fetch_live_project_inventory",
                return_value=([], []),
            ),
            patch(
                "app.api.tasks.list_endpoints.task_store.list_tasks",
                side_effect=_fake_list_tasks,
            ),
            patch(
                "app.api.tasks.list_endpoints.has_active_checkpoint",
                side_effect=lambda task_id, project_id=None: (
                    project_id == test_project_id
                    and task_id in {
                        "task-ready-checkpoint",
                        "task-pending-checkpoint",
                        "task-running-checkpoint",
                    }
                ),
            ),
        ):
            response = client.get("/api/tasks/ready-all?limit=3")

        assert response.status_code == 200
        payload = response.json()
        assert payload["payload"]["summary"] == {
            "ready": 0,
            "blocked": 0,
            "active": 2,
            "stale": 0,
            "projects": 1,
        }
        assert "task-ready-checkpoint" not in payload["raw"]
        assert "~ task-pending-checkpoint" in payload["raw"]
        assert "~ task-running-checkpoint" in payload["raw"]

    def test_project_ready_all_overview_scopes_to_requested_project(
        self,
        client: Any,
        test_project_id: str,
    ) -> None:
        with (
            patch(
                "app.api.tasks.list_endpoints.project_store.list_projects",
                return_value=[
                    {"id": test_project_id, "name": test_project_id},
                    {"id": "other-project", "name": "other-project"},
                ],
            ),
            patch(
                "app.api.tasks.list_endpoints._collect_ready_all_project_data",
                return_value={
                    "project_id": test_project_id,
                    "project_name": test_project_id,
                    "ready_tasks": [],
                    "ready_count": 0,
                    "blocked_tasks": [],
                    "blocked_count": 0,
                    "active_tasks": [],
                    "active_count": 0,
                    "stale_tasks": [],
                    "stale_count": 0,
                },
            ) as mock_collect,
        ):
            response = client.get(f"/api/projects/{test_project_id}/tasks/ready-all?limit=2")

        assert response.status_code == 200
        payload = response.json()
        assert payload["payload"]["summary"]["projects"] == 1
        mock_collect.assert_called_once_with(test_project_id, test_project_id, 2)

    def test_create_task_stays_draft_when_execution_details_missing(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Draft feature task",
                "description": "Implement health endpoint",
                "task_type": "feature",
                "complexity": "STANDARD",
            },
        )
        assert response.status_code == 200
        task = response.json()
        cleanup_task(task["id"])

        assert task["plan_status"] in (None, "draft")


class TestTaskDelete:
    def test_delete_task_archives_snapshot(self, client: Any, test_project_id: str) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Delete through API",
                "description": "Preserve archived snapshot",
                "task_type": "task",
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]

        response = client.delete(f"/api/projects/{test_project_id}/tasks/{task_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

        archived = task_store.get_deleted_task_context(task_id)
        assert archived is not None
        assert archived["task"]["title"] == "Delete through API"
        assert archived["task"]["deletion_source"] == "api:tasks.delete_task"
