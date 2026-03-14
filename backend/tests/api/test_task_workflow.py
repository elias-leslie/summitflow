"""Integration tests for task workflow API endpoints.

Tests for:
- POST /approve: Plan approval workflow
- GET /context: Full task context (TOON format)
- GET /export: Complete task JSON for plan.json round-trip
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from app.services.task_lane_preflight import TaskLaneConflictCheck
from app.storage.connection import get_connection


class TestApproveEndpoint:
    """Test POST /approve endpoint."""

    def test_approve_task_with_spirit(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
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

    def test_approve_task_without_spirit(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
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

    def test_approve_nonexistent_task(self, client: Any, test_project_id: str) -> None:
        """Approving a nonexistent task should return 404."""
        response = client.post(f"/api/projects/{test_project_id}/tasks/task-nonexistent/approve")
        assert response.status_code == 404


class TestContextEndpoint:
    """Test GET /context endpoint."""

    def test_context_returns_toon_by_default(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
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
        assert "TITLE:Test task for context" in content
        assert "DESCRIPTION:Testing context endpoint" in content
        assert "WORKFLOW:plan:draft|ready:no|issues:" in content
        assert "READINESS:missing:objective,done_when,spirit_anti,subtasks" in content
        assert "CRITERIA[0]:0/0" not in content

    @patch("app.api.tasks.workflow.check_task_lane_conflicts")
    def test_context_includes_lane_overlap_summary_when_present(
        self,
        mock_lane_check: Any,
        client: Any,
        test_project_id: str,
        cleanup_task: Callable[[str], None],
    ) -> None:
        mock_lane_check.return_value = TaskLaneConflictCheck(
            issues=["Another active coding lane is already modifying shared plumbing"],
            conflicting_tasks=["task-999"],
            overlap_kind="shared_plumbing",
            overlap_paths=["backend/app/services/tools/catalog.py"],
            shared_plumbing=True,
            disposition="block",
            owner_location="worktree /tmp/worktrees/task-999",
        )

        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task for lane summary",
                "description": "Testing context overlap surfacing",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/context")
        assert response.status_code == 200
        assert (
            "LANE:disp:block | kind:shared_plumbing | tasks:task-999 | "
            "owner:worktree /tmp/worktrees/task-999 | "
            "paths:backend/app/services/tools/catalog.py | shared:yes"
            in response.text
        )

    def test_context_returns_json_when_requested(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
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
        assert data["lane_preflight"] == {
            "issues": [],
            "suggestions": [],
            "conflicting_tasks": [],
            "overlap_kind": None,
            "overlap_paths": [],
            "shared_plumbing": False,
            "disposition": "allow",
            "owner_session_id": None,
            "owner_branch": None,
            "owner_location": None,
            "active_specialists": [],
        }

    @patch("app.api.tasks.workflow.check_task_lane_conflicts")
    def test_context_json_includes_lane_overlap_payload_when_present(
        self,
        mock_lane_check: Any,
        client: Any,
        test_project_id: str,
        cleanup_task: Callable[[str], None],
    ) -> None:
        mock_lane_check.return_value = TaskLaneConflictCheck(
            issues=["Another active coding lane overlaps exact files"],
            suggestions=["Finish the active lane first"],
            conflicting_tasks=["task-999"],
            overlap_kind="exact_file",
            overlap_paths=["backend/app/foo.py"],
            shared_plumbing=False,
            disposition="block",
            owner_session_id="sess-123",
            owner_branch="task-999/main",
            owner_location="repo /home/testuser/summitflow",
        )

        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task for context JSON overlap",
                "description": "Testing JSON overlap surfacing",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        response = client.get(
            f"/api/projects/{test_project_id}/tasks/{task_id}/context",
            params={"format": "json"},
        )
        assert response.status_code == 200
        assert response.json()["lane_preflight"] == {
            "issues": ["Another active coding lane overlaps exact files"],
            "suggestions": ["Finish the active lane first"],
            "conflicting_tasks": ["task-999"],
            "overlap_kind": "exact_file",
            "overlap_paths": ["backend/app/foo.py"],
            "shared_plumbing": False,
            "disposition": "block",
            "owner_session_id": "sess-123",
            "owner_branch": "task-999/main",
            "owner_location": "repo /home/testuser/summitflow",
            "active_specialists": [],
        }

    def test_context_includes_subtasks(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
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

    def test_export_returns_complete_task_data(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
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
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
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

    def test_export_nonexistent_task(self, client: Any, test_project_id: str) -> None:
        """Exporting a nonexistent task should return 404."""
        response = client.get(f"/api/projects/{test_project_id}/tasks/task-nonexistent/export")
        assert response.status_code == 404


class TestTaskStatusEndpoint:
    """Test PATCH /status behavior for admin-like closes."""

    def test_status_patch_skip_gates_completes_pending_task(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        """skip_gates should allow pending planning/meta tasks to close cleanly."""
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Pending meta task",
                "description": "Can close without claim",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task = response.json()
        task_id = task["id"]
        cleanup_task(task_id)

        response = client.patch(
            f"/api/projects/{test_project_id}/tasks/{task_id}/status",
            json={"status": "completed", "skip_gates": True, "reason": "meta shipped"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
