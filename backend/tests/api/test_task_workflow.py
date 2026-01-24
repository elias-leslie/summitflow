"""Integration tests for task workflow API endpoints.

Tests for:
- POST /approve: Plan approval workflow
- GET /context: Full task context (TOON format)
- GET /export: Complete task JSON for plan.json round-trip
"""

import json

from app.storage.connection import get_connection


class TestApproveEndpoint:
    """Test POST /approve endpoint."""

    def test_approve_task_with_spirit(self, client, test_project_id, cleanup_task):
        """Approving a task with existing spirit data should succeed."""
        # Create a task
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task for approval",
                "description": "Testing approval workflow",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        # Add spirit data
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_spirit (task_id, objective, plan_status)
                VALUES (%s, %s, %s)
                """,
                (task_id, "Test objective", "draft"),
            )
            conn.commit()

        # Approve the plan
        response = client.post(
            f"/api/projects/{test_project_id}/tasks/{task_id}/approve",
            json={"approved_by": "test-user", "notes": "Looks good"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["task_id"] == task_id
        assert data["plan_status"] == "approved"
        assert data["plan_approved_by"] == "test-user"
        assert data["plan_approved_at"] is not None

    def test_approve_task_without_spirit(self, client, test_project_id, cleanup_task):
        """Approving a task without spirit data should create spirit and approve."""
        # Create a task (no spirit data)
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task without spirit",
                "description": "Testing approval creates spirit",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        # Approve the plan (should create spirit record)
        response = client.post(f"/api/projects/{test_project_id}/tasks/{task_id}/approve")
        assert response.status_code == 200
        data = response.json()

        assert data["task_id"] == task_id
        assert data["plan_status"] == "approved"
        assert data["plan_approved_by"] == "user"  # Default

    def test_approve_nonexistent_task(self, client, test_project_id):
        """Approving a nonexistent task should return 404."""
        response = client.post(f"/api/projects/{test_project_id}/tasks/task-nonexistent/approve")
        assert response.status_code == 404


class TestContextEndpoint:
    """Test GET /context endpoint."""

    def test_context_returns_toon_by_default(self, client, test_project_id, cleanup_task):
        """Context endpoint should return TOON format by default."""
        # Create a task
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task for context",
                "description": "Testing context endpoint",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        # Get context (TOON format by default)
        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/context")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"

        content = response.text
        assert content.startswith("TASK:")
        assert task_id in content

    def test_context_returns_json_when_requested(self, client, test_project_id, cleanup_task):
        """Context endpoint should return JSON when format=json."""
        # Create a task
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task for context JSON",
                "description": "Testing JSON format",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        # Get context as JSON
        response = client.get(
            f"/api/projects/{test_project_id}/tasks/{task_id}/context",
            params={"format": "json"},
        )
        assert response.status_code == 200
        data = response.json()

        assert "task" in data
        assert data["task"]["id"] == task_id
        assert "spirit" in data
        assert "subtasks" in data
        assert "blockers" in data

    def test_context_includes_subtasks(self, client, test_project_id, cleanup_task):
        """Context should include subtask details."""
        # Create a task
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task with subtasks",
                "description": "Testing subtask inclusion",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        # Create a subtask
        response = client.post(
            f"/api/projects/{test_project_id}/tasks/{task_id}/subtasks",
            json={
                "subtask_id": "1.1",
                "description": "First subtask",
                "steps": [
                    {
                        "description": "Step 1",
                        "verify_command": "echo test",
                        "expected_output": "test",
                    }
                ],
            },
        )
        assert response.status_code == 201  # 201 Created for POST

        # Get context and verify subtask is included
        response = client.get(
            f"/api/projects/{test_project_id}/tasks/{task_id}/context",
            params={"format": "json"},
        )
        assert response.status_code == 200
        data = response.json()

        assert len(data["subtasks"]) == 1
        assert data["subtasks"][0]["subtask_id"] == "1.1"


class TestExportEndpoint:
    """Test GET /export endpoint."""

    def test_export_returns_complete_task_data(self, client, test_project_id, cleanup_task):
        """Export should return complete task data for plan.json round-trip."""
        # Create a task
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task for export",
                "description": "Testing export endpoint",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        # Add spirit data
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_spirit (task_id, objective, spirit_anti, done_when)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (
                    task_id,
                    "Export objective",
                    "SPIRIT: Test. ANTI: Don't fail.",
                    json.dumps(["Condition 1", "Condition 2"]),
                ),
            )
            conn.commit()

        # Get export
        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/export")
        assert response.status_code == 200
        data = response.json()

        # Verify structure
        assert "task" in data
        assert data["task"]["id"] == task_id
        assert "spirit" in data
        assert data["spirit"]["objective"] == "Export objective"
        assert "acceptance_criteria" in data
        assert "subtasks" in data
        assert "dependencies" in data
        assert "progress_log" in data

    def test_export_includes_acceptance_criteria_from_done_when(
        self, client, test_project_id, cleanup_task
    ):
        """Export should convert done_when to acceptance_criteria."""
        # Create a task
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task with done_when",
                "description": "Testing AC conversion",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        # Add spirit data with done_when
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_spirit (task_id, objective, done_when)
                VALUES (%s, %s, %s::jsonb)
                """,
                (
                    task_id,
                    "Test",
                    json.dumps(["First condition", "Second condition"]),
                ),
            )
            conn.commit()

        # Get export
        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/export")
        assert response.status_code == 200
        data = response.json()

        # Verify acceptance_criteria
        ac = data["acceptance_criteria"]
        assert len(ac) == 2
        assert ac[0]["id"] == "ac-1"
        assert ac[0]["criterion"] == "First condition"
        assert ac[1]["id"] == "ac-2"
        assert ac[1]["criterion"] == "Second condition"

    def test_export_nonexistent_task(self, client, test_project_id):
        """Exporting a nonexistent task should return 404."""
        response = client.get(f"/api/projects/{test_project_id}/tasks/task-nonexistent/export")
        assert response.status_code == 404
