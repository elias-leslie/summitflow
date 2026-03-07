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

    def test_update_task_persists_labels(
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
