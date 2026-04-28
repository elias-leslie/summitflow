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
from app.storage.events import log_task_event


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
                INSERT INTO task_spirit (task_id, plan_status)
                VALUES (%s, %s)
                """,
                (task_id, "draft"),
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
        assert "READINESS:missing:" in content
        assert "done_when" in content
        assert "subtasks" in content
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
            issues=["Another active coding session is already modifying shared plumbing"],
            conflicting_tasks=["task-999"],
            overlap_kind="shared_plumbing",
            overlap_paths=["backend/app/services/tools/catalog.py"],
            shared_plumbing=True,
            disposition="block",
            owner_location="checkout /tmp/lanes/task-999",
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
            "owner:checkout /tmp/lanes/task-999 | "
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

    def test_context_exposes_additive_continuity_contract(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task for continuity",
                "description": "Testing additive continuity contract",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        response = client.post(
            f"/api/projects/{test_project_id}/tasks/{task_id}/subtasks",
            json={
                "subtask_id": "2.1",
                "description": "Render continuity block",
                "steps": [{"description": "Wire logs"}],
            },
        )
        assert response.status_code == 201

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_spirit (task_id, context)
                VALUES (%s, %s::jsonb)
                ON CONFLICT (task_id)
                DO UPDATE SET context = task_spirit.context || EXCLUDED.context
                """,
                (
                    task_id,
                    json.dumps(
                        {
                            "objective": "Make resume reliable",
                            "files_to_modify": ["backend/cli/commands/tasks_context.py"],
                        }
                    ),
                ),
            )
            conn.commit()

        log_task_event(task_id, "Started continuity audit")
        log_task_event(task_id, "Wired logs")

        toon = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/context")
        assert toon.status_code == 200
        assert "OBJECTIVE:Make resume reliable" in toon.text
        assert "CURRENT_SLICE:2.1 Render continuity block" in toon.text
        assert "BLOCKERS:none explicit" in toon.text
        assert "RECENT_PROGRESS[2]" in toon.text
        assert "NEXT_ACTION:2.1.1 Wire logs" in toon.text
        assert "KEY_FILES[1]:backend/cli/commands/tasks_context.py" in toon.text

        response = client.get(
            f"/api/projects/{test_project_id}/tasks/{task_id}/context",
            params={"format": "json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["continuity"] == {
            "objective": "Make resume reliable",
            "current_slice": "2.1 Render continuity block",
            "blockers": [],
            "recent_progress": data["continuity"]["recent_progress"],
            "next_action": "2.1.1 Wire logs",
            "key_files": ["backend/cli/commands/tasks_context.py"],
        }
        assert len(data["continuity"]["recent_progress"]) == 2
        assert data["continuity"]["recent_progress"][0].endswith("Started continuity audit")
        assert data["continuity"]["recent_progress"][1].endswith("Wired logs")

    def test_context_hides_execution_readiness_noise_for_completed_task(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Completed redesign task",
                "description": "Completed context should stay focused.",
                "task_type": "feature",
                "priority": 1,
                "complexity": "COMPLEX",
                "labels": ["auth"],
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tasks
                SET status = %s, complexity = %s, priority = %s, task_type = %s, labels = %s
                WHERE id = %s
                """,
                (
                    "completed",
                    "COMPLEX",
                    1,
                    "feature",
                    ["auth"],
                    task_id,
                ),
            )
            cur.execute(
                """
                UPDATE task_spirit
                SET done_when = %s::jsonb,
                    context = %s::jsonb,
                    plan_status = %s,
                    complexity = %s
                WHERE task_id = %s
                """,
                (
                    json.dumps(["Task merged safely"]),
                    json.dumps(
                        {
                            "files_to_modify": ["backend/app/api/tasks/workflow.py"],
                            "testing_strategy": "Run context output coverage",
                            "second_opinion": {
                                "required": True,
                                "stage": "both",
                                "status": "pending",
                            },
                        }
                    ),
                    "draft",
                    "COMPLEX",
                    task_id,
                ),
            )
            conn.commit()

        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/context")
        assert response.status_code == 200

        content = response.text
        assert "WORKFLOW:" not in content
        assert "READINESS:" not in content
        assert "2nd:" not in content
        assert "CONTEXT:modify:backend/app/api/tasks/workflow.py | testing:Run context output coverage" in content

    @patch("app.api.tasks.workflow.check_task_lane_conflicts")
    def test_context_json_includes_lane_overlap_payload_when_present(
        self,
        mock_lane_check: Any,
        client: Any,
        test_project_id: str,
        cleanup_task: Callable[[str], None],
    ) -> None:
        mock_lane_check.return_value = TaskLaneConflictCheck(
            issues=["Another active coding session overlaps exact files"],
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
            "issues": ["Another active coding session overlaps exact files"],
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

    def test_task_update_shape_persists_plan_context_subtask_steps_into_context(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        """Task updates should persist plan-context subtasks and unblock readiness rendering."""
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Task update plan context",
                "description": "Verify rich update shape persists",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        update_response = client.patch(
            f"/api/projects/{test_project_id}/tasks/{task_id}",
            json={
                "objective": "Carry planner context through task updates",
                "constraints": ["Keep existing task ids stable"],
                "done_when": ["Rendered context includes planned step verification"],
                "files_to_modify": ["backend/app/api/tasks/update_endpoints.py"],
                "testing_strategy": "Patch task, then read context JSON",
                "subtasks": [
                    {
                        "subtask_id": "1.2",
                        "description": "Persist update payload into context",
                        "steps": [
                            {
                                "description": "Store normalized step shape",
                                "spec": {"verify_command": "dt pytest backend/tests/api/test_task_workflow.py"},
                            },
                            "Confirm readiness no longer reports missing subtasks",
                        ],
                    }
                ],
            },
        )
        assert update_response.status_code == 200

        toon_response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/context")
        assert toon_response.status_code == 200
        assert "OBJECTIVE:Carry planner context through task updates" in toon_response.text
        assert (
            "CONTEXT:modify:backend/app/api/tasks/update_endpoints.py | "
            "testing:Patch task, then read context JSON" in toon_response.text
        )

        response = client.get(
            f"/api/projects/{test_project_id}/tasks/{task_id}/context",
            params={"format": "json"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["continuity"]["objective"] == "Carry planner context through task updates"
        assert data["spirit"]["done_when"] == ["Rendered context includes planned step verification"]
        assert data["spirit"]["context"]["objective"] == "Carry planner context through task updates"
        assert data["spirit"]["context"]["constraints"] == ["Keep existing task ids stable"]
        assert data["spirit"]["context"]["subtasks"] == [
            {
                "subtask_id": "1.2",
                "description": "Persist update payload into context",
                "steps": [
                    {
                        "step_number": 1,
                        "description": "Store normalized step shape",
                        "passes": False,
                        "spec": {"verify_command": "dt pytest backend/tests/api/test_task_workflow.py"},
                    },
                    {
                        "step_number": 2,
                        "description": "Confirm readiness no longer reports missing subtasks",
                        "passes": False,
                    },
                ],
            }
        ]
        assert data["spirit"]["context"]["files_to_modify"] == ["backend/app/api/tasks/update_endpoints.py"]
        assert data["spirit"]["context"]["testing_strategy"] == "Patch task, then read context JSON"


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

        response = client.post(
            f"/api/projects/{test_project_id}/tasks/{task_id}/subtasks",
            json={
                "subtask_id": "1.1",
                "description": "First subtask",
                "steps": [
                    {
                        "description": "Step 1",
                        "spec": {"verify_command": "dt pytest backend/tests/api/test_task_workflow.py"},
                    }
                ],
            },
        )
        assert response.status_code == 201

        # Add spirit data
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_spirit (task_id, done_when, context, plan_status, complexity)
                VALUES (%s, %s::jsonb, %s::jsonb, %s, %s)
                ON CONFLICT (task_id)
                DO UPDATE SET
                    done_when = EXCLUDED.done_when,
                    context = task_spirit.context || EXCLUDED.context,
                    plan_status = EXCLUDED.plan_status,
                    complexity = EXCLUDED.complexity
                """,
                (
                    task_id,
                    json.dumps(["Condition 1", "Condition 2"]),
                    json.dumps(
                        {
                            "objective": "Restore complete export fidelity",
                            "spirit_anti": "Do not drop plan context during export.",
                            "constraints": ["Keep export shape stable"],
                            "files_to_modify": ["backend/app/api/tasks/workflow_export.py"],
                            "testing_strategy": "Use the export endpoint as the source of truth.",
                            "subtasks": [
                                {
                                    "subtask_id": "1.1",
                                    "description": "First subtask",
                                    "steps": [
                                        {
                                            "step_number": 1,
                                            "description": "Step 1",
                                            "passes": False,
                                            "spec": {
                                                "verify_command": "dt pytest backend/tests/api/test_task_workflow.py"
                                            },
                                        }
                                    ],
                                }
                            ],
                        }
                    ),
                    "approved",
                    "COMPLEX",
                ),
            )
            conn.commit()

        # Get export
        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/export")
        assert response.status_code == 200
        data = response.json()

        # Verify structure
        assert "exported_at" in data
        assert "task" in data
        assert data["task"]["id"] == task_id
        assert data["task"]["objective"] == "Restore complete export fidelity"
        assert data["task"]["spirit_anti"] == "Do not drop plan context during export."
        assert data["task"]["constraints"] == ["Keep export shape stable"]
        assert data["task"]["files_to_modify"] == ["backend/app/api/tasks/workflow_export.py"]
        assert data["task"]["testing_strategy"] == "Use the export endpoint as the source of truth."
        assert data["task"]["plan_status"] == "approved"
        assert data["task"]["complexity"] == "COMPLEX"
        assert "spirit" in data
        assert data["spirit"]["done_when"] == ["Condition 1", "Condition 2"]
        assert data["spirit"]["objective"] == "Restore complete export fidelity"
        assert data["spirit"]["constraints"] == ["Keep export shape stable"]
        assert "acceptance_criteria" not in data
        assert "subtasks" in data
        assert data["subtasks"][0]["subtask_id"] == "1.1"
        assert data["subtasks"][0]["steps"][0]["description"] == "Step 1"
        assert data["subtasks"][0]["steps"][0]["spec"] == {
            "verify_command": "dt pytest backend/tests/api/test_task_workflow.py"
        }
        assert "dependencies" in data
        assert "progress_log" in data

    def test_export_keeps_done_when_canonical(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        """Export should keep done_when and omit synthetic acceptance_criteria."""
        # Create a task
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Test task with done_when",
                "description": "Testing done_when export",
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
                INSERT INTO task_spirit (task_id, done_when)
                VALUES (%s, %s::jsonb)
                """,
                (
                    task_id,
                    json.dumps(["First condition", "Second condition"]),
                ),
            )
            conn.commit()

        # Get export
        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/export")
        assert response.status_code == 200
        data = response.json()

        assert data["task"]["done_when"] == ["First condition", "Second condition"]
        assert data["spirit"]["done_when"] == ["First condition", "Second condition"]
        assert "acceptance_criteria" not in data

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

    def test_status_patch_pauses_and_resumes_task(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Pausable task",
                "description": "Can be tabled without completion",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        response = client.patch(
            f"/api/projects/{test_project_id}/tasks/{task_id}/status",
            json={"status": "paused", "reason": "waiting"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "paused"

        response = client.patch(
            f"/api/projects/{test_project_id}/tasks/{task_id}/status",
            json={"status": "pending", "reason": "ready"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "pending"


    def test_export_preserves_raw_task_status_and_second_opinion_shape(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Closeout truth export fixture",
                "description": "Completed task should export raw lifecycle status.",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        raw_second_opinion = {
            "required": True,
            "stage": "task_shape",
            "status": "needs_revision",
            "summary": "Old shaping note.",
            "reviews": {
                "task_shape": {
                    "required": True,
                    "stage": "task_shape",
                    "status": "needs_revision",
                    "summary": "Old shaping note.",
                },
                "pre_close": {
                    "required": True,
                    "stage": "pre_close",
                    "status": "completed",
                    "summary": "Ready to close.",
                    "verdict": "APPROVED",
                    "reviewed_by_agent": "specifier",
                    "reviewed_at": "2026-01-01T00:00:00+00:00",
                },
            },
        }

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE tasks SET status = %s WHERE id = %s", ("completed", task_id))
            cur.execute(
                """
                INSERT INTO task_spirit (task_id, done_when, context, plan_status)
                VALUES (%s, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (task_id) DO UPDATE SET
                    done_when = EXCLUDED.done_when,
                    context = EXCLUDED.context,
                    plan_status = EXCLUDED.plan_status
                """,
                (
                    task_id,
                    json.dumps(["All subtasks pass", "Closeout proof logged"]),
                    json.dumps({
                        "second_opinion": raw_second_opinion,
                        "files_to_modify": ["backend/app/api/tasks/workflow_export.py"],
                    }),
                    "draft",
                ),
            )
            conn.commit()

        for subtask_id in ("1.1", "1.2"):
            subtask_response = client.post(
                f"/api/projects/{test_project_id}/tasks/{task_id}/subtasks",
                json={"subtask_id": subtask_id, "description": f"Subtask {subtask_id}"},
            )
            assert subtask_response.status_code == 201
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE task_subtasks SET passes = TRUE WHERE task_id = %s AND subtask_id = %s",
                    (task_id, subtask_id),
                )
                conn.commit()

        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/export")
        assert response.status_code == 200
        data = response.json()

        assert data["task"]["status"] == "completed"
        assert data["spirit"]["plan_status"] == "draft"
        assert data["task"]["plan_status"] == "draft"
        assert data["task"]["context"]["second_opinion"] == raw_second_opinion
        assert data["spirit"]["context"]["second_opinion"] == raw_second_opinion

    def test_export_keeps_null_task_status_when_storage_status_missing(
        self, client: Any, test_project_id: str, cleanup_task: Callable[[str], None]
    ) -> None:
        response = client.post(
            f"/api/projects/{test_project_id}/tasks",
            json={
                "title": "Null status export fixture",
                "description": "Null task status should stay null.",
                "task_type": "task",
                "priority": 2,
            },
        )
        assert response.status_code == 200
        task_id = response.json()["id"]
        cleanup_task(task_id)

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE tasks SET status = NULL WHERE id = %s", (task_id,))
            cur.execute(
                """
                INSERT INTO task_spirit (task_id, plan_status, context)
                VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (task_id) DO UPDATE SET
                    plan_status = EXCLUDED.plan_status,
                    context = EXCLUDED.context
                """,
                (task_id, "draft", json.dumps({"second_opinion": {"stage": "task_shape", "status": "pending"}})),
            )
            conn.commit()

        response = client.get(f"/api/projects/{test_project_id}/tasks/{task_id}/export")
        assert response.status_code == 200
        data = response.json()

        assert data["task"]["status"] is None
        assert data["spirit"]["plan_status"] == "draft"
