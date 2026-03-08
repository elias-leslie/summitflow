"""Integration tests for task_spirit JOIN in tasks API.

Tests verify that:
1. Task with spirit data returns objective, spirit_anti, decisions, constraints, done_when
2. Task without spirit data returns null/empty for spirit fields
3. List endpoint returns spirit fields for all tasks
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from app.storage.connection import get_connection


class TestTaskSpiritJoin:
    """Test task_spirit LEFT JOIN functionality."""

    def test_get_task_with_spirit_data(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        """Task with spirit data should return all spirit fields populated."""
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
        # Note: decisions is list[dict], not list[str]
        decisions_data = [
            {"id": "d1", "question": "API style?", "answer": "Use REST API"},
            {"id": "d2", "question": "Storage?", "answer": "Store in PostgreSQL"},
        ]
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_spirit (task_id, objective, spirit_anti, decisions, constraints, done_when, plan_status)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    task_id,
                    "Complete the feature implementation",
                    "Do NOT break existing tests",
                    json.dumps(decisions_data),
                    json.dumps(["Must be backward compatible"]),
                    json.dumps(["All tests pass", "PR merged"]),
                    "approved",
                ),
            )
            conn.commit()

        # Fetch task and verify spirit fields
        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}")
        assert response.status_code == 200
        task_data = response.json()

        assert task_data["objective"] == "Complete the feature implementation"
        assert task_data["spirit_anti"] == "Do NOT break existing tests"
        assert task_data["decisions"] == decisions_data
        assert task_data["constraints"] == ["Must be backward compatible"]
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
        assert task_data["objective"] is None
        assert task_data["spirit_anti"] is None
        assert task_data["decisions"] == [] or task_data["decisions"] is None
        assert task_data["constraints"] == [] or task_data["constraints"] is None
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
                INSERT INTO task_spirit (task_id, objective, spirit_anti, plan_status)
                VALUES (%s, %s, %s, %s)
                """,
                (task1_id, "List test objective", "List test anti-pattern", "draft"),
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
        assert task1_data["objective"] == "List test objective"
        assert task1_data["spirit_anti"] == "List test anti-pattern"
        assert task1_data["plan_status"] == "draft"

        # Verify spirit fields are null on task without spirit
        assert task2_data["objective"] is None
        assert task2_data["spirit_anti"] is None


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
        assert updated["autonomous"] is False

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

    def test_ready_endpoint_filters_out_execution_unready_tasks(
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
            "objective": None,
            "acceptance_criteria": None,
            "current_phase": None,
            "verification_result": None,
            "spirit_anti": None,
            "decisions": [],
            "constraints": [],
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
            "worktree": None,
        }
        ready_task = {
            **draft_task,
            "id": "task-ready",
            "title": "Ready bug task",
            "task_type": "bug",
            "priority": 1,
            "objective": "Restore 200 on /health",
            "done_when": ["GET /health returns 200", "Relevant tests pass"],
            "complexity": "SIMPLE",
            "plan_status": "approved",
        }

        def _fake_sync(task_id: str):
            class _Readiness:
                def __init__(self, ready: bool):
                    self.ready = ready

            return _Readiness(task_id == "task-ready")

        with (
            patch(
                "app.api.tasks.list_endpoints.task_store.list_ready_tasks",
                return_value=[draft_task, ready_task],
            ),
            patch(
                "app.services.task_execution_readiness.sync_task_execution_readiness",
                side_effect=_fake_sync,
            ),
            patch(
                "app.api.tasks.list_endpoints.get_step_counts_batch",
                return_value={"task-ready": 0},
            ),
        ):
            response = client.get(f"/api/projects/{test_project_id}/tasks/ready?limit=20")

        assert response.status_code == 200
        tasks = response.json()["tasks"]
        task_ids = {task["id"] for task in tasks}

        assert "task-ready" in task_ids
        assert "task-draft" not in task_ids

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
