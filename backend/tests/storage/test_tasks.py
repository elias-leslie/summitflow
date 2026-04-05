"""Unit tests for tasks storage layer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.storage import subtasks as subtask_store
from app.storage import tasks as task_store
from app.storage.connection import get_connection
from app.storage.tasks.status import VALID_TRANSITIONS


@pytest.fixture
def project_id(ensure_test_project: str) -> str:
    """Use test project from conftest."""
    return ensure_test_project


@pytest.fixture
def test_task(project_id: str, cleanup_task: Callable[[str], None]) -> dict[str, Any]:
    """Create and cleanup a test task with approved spirit record.

    Note: G4 enforcement (migration 074) requires spirit record with approved plan
    before task can transition to 'running' status.
    """
    task = task_store.create_task(
        project_id=project_id,
        title="Test Task for Storage Tests",
        description="Created by test fixture",
    )
    cleanup_task(task["id"])

    # Create spirit record with approved plan (required by G4 enforcement)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO task_spirit (task_id, plan_status, complexity)
            VALUES (%s, 'approved', 'SIMPLE')
            ON CONFLICT (task_id) DO UPDATE SET plan_status = 'approved'
            """,
            (task["id"],),
        )
        conn.commit()

    return task


class TestValidTransitions:
    """Unit tests for VALID_TRANSITIONS state machine (no DB needed)."""

    @pytest.mark.parametrize("state", ["pending", "running", "failed", "cancelled"])
    def test_all_non_terminal_states_exist_in_valid_transitions(self, state: str) -> None:
        """Every valid status must have an entry in VALID_TRANSITIONS."""
        assert state in VALID_TRANSITIONS, (
            f"State '{state}' missing from VALID_TRANSITIONS"
        )

    def test_final_states_keep_truthful_recovery_paths(self) -> None:
        """Final states should support the recovery paths the CLI relies on."""
        assert VALID_TRANSITIONS["completed"] == {"pending", "cancelled"}
        assert VALID_TRANSITIONS["failed"] == {"pending", "running", "cancelled", "completed"}
        assert VALID_TRANSITIONS["cancelled"] == {"pending"}


class TestCreateTask:
    """Tests for create_task function."""

    def test_create_task_generates_valid_id(self, project_id: str, cleanup_task: Callable[[str], None]) -> None:
        """Test that create_task generates a valid task_id."""
        task = task_store.create_task(
            project_id=project_id,
            title="Test Create",
        )
        cleanup_task(task["id"])

        assert task is not None
        assert task["id"].startswith("task-")
        assert len(task["id"]) == 13  # "task-" + 8 hex chars
        assert task["status"] == "pending"
        assert task["project_id"] == project_id

    def test_create_task_with_custom_id(self, project_id: str, cleanup_task: Callable[[str], None]) -> None:
        """Test creating task with custom ID."""
        custom_id = "task-custom-123"
        task = task_store.create_task(
            project_id=project_id,
            title="Custom ID Task",
            task_id=custom_id,
        )
        cleanup_task(task["id"])

        assert task["id"] == custom_id

    def test_create_task_with_all_fields(self, project_id: str, cleanup_task: Callable[[str], None]) -> None:
        """Test creating task with all optional fields."""
        task = task_store.create_task(
            project_id=project_id,
            title="Full Task",
            description="Full description",
            capability_id=None,  # Optional capability link
        )
        cleanup_task(task["id"])

        assert task["title"] == "Full Task"
        assert task["description"] == "Full description"
        assert task["capability_id"] is None


class TestUpdateTaskStatus:
    """Tests for update_task_status function."""

    def test_status_pending_to_running(self, test_task: dict[str, Any]) -> None:
        """Test transition from pending to running sets started_at."""
        result = task_store.update_task_status(test_task["id"], "running")

        assert result is not None
        assert result["status"] == "running"
        assert result["started_at"] is not None

    def test_status_running_to_completed(self, test_task: dict[str, Any]) -> None:
        """Test transition from running to completed sets completed_at."""
        task_store.update_task_status(test_task["id"], "running")
        result = task_store.update_task_status(test_task["id"], "completed")

        assert result is not None
        assert result["status"] == "completed"
        assert result["completed_at"] is not None

    def test_status_running_to_failed_with_error(self, test_task: dict[str, Any]) -> None:
        """Test transition to failed with error message."""
        task_store.update_task_status(test_task["id"], "running")
        result = task_store.update_task_status(
            test_task["id"], "failed", error_message="Test error"
        )

        assert result is not None
        assert result["status"] == "failed"
        assert result["error_message"] == "Test error"
        assert result["completed_at"] is not None

    def test_status_pending_to_completed_allowed_when_transition_validation_skipped(
        self, test_task: dict[str, Any]
    ) -> None:
        """Admin should be able to complete pending tasks without claiming."""
        result = task_store.update_task_status(
            test_task["id"],
            "completed",
            validate_transition=False,
        )

        assert result is not None
        assert result["status"] == "completed"
        assert result["completed_at"] is not None

    def test_status_failed_to_running_retries_task(self, test_task: dict[str, Any]) -> None:
        """Test transition from failed to running (retry a failed task)."""
        task_store.update_task_status(test_task["id"], "running")
        task_store.update_task_status(test_task["id"], "failed")
        result = task_store.update_task_status(test_task["id"], "running")

        assert result is not None
        assert result["status"] == "running"
        assert result["completed_at"] is None

    def test_status_failed_to_cancelled_allowed(self, test_task: dict[str, Any]) -> None:
        """Failed tasks should be abandonable without lying about the final state."""
        task_store.update_task_status(test_task["id"], "running")
        task_store.update_task_status(test_task["id"], "failed")

        result = task_store.update_task_status(test_task["id"], "cancelled")

        assert result is not None
        assert result["status"] == "cancelled"
        assert result["completed_at"] is not None

    def test_status_failed_to_completed_allowed(self, test_task: dict[str, Any]) -> None:
        """Merged recovery should be able to finalize a previously failed task."""
        task_store.update_task_status(test_task["id"], "running")
        task_store.update_task_status(test_task["id"], "failed")

        result = task_store.update_task_status(test_task["id"], "completed")

        assert result is not None
        assert result["status"] == "completed"
        assert result["completed_at"] is not None

    def test_status_completed_to_cancelled_allowed(self, test_task: dict[str, Any]) -> None:
        """Discarding stale completed work should leave the task truthful."""
        task_store.update_task_status(test_task["id"], "running")
        task_store.update_task_status(test_task["id"], "completed")

        result = task_store.update_task_status(test_task["id"], "cancelled")

        assert result is not None
        assert result["status"] == "cancelled"
        assert result["completed_at"] is not None

    def test_status_cancelled_to_pending_reopens_task(self, test_task: dict[str, Any]) -> None:
        """Cancelled tasks should be reopenable."""
        task_store.update_task_status(test_task["id"], "cancelled")

        result = task_store.update_task_status(test_task["id"], "pending")

        assert result is not None
        assert result["status"] == "pending"

    def test_status_completed_to_pending_clears_completed_at(
        self, test_task: dict[str, Any]
    ) -> None:
        """Reopened tasks should not retain stale aterm timestamps."""
        task_store.update_task_status(test_task["id"], "running")
        task_store.update_task_status(test_task["id"], "completed")

        result = task_store.update_task_status(test_task["id"], "pending")

        assert result is not None
        assert result["status"] == "pending"
        assert result["completed_at"] is None

    def test_invalid_status_raises_error(self, test_task: dict[str, Any]) -> None:
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            task_store.update_task_status(test_task["id"], "invalid_status")


class TestListTasks:
    """Tests for list_tasks function."""

    def test_list_tasks_returns_all(self, project_id: str, cleanup_task: Callable[[str], None]) -> None:
        """Test listing all tasks for a project."""
        task1 = task_store.create_task(project_id, "Task 1")
        task2 = task_store.create_task(project_id, "Task 2")
        cleanup_task(task1["id"])
        cleanup_task(task2["id"])

        tasks = task_store.list_tasks(project_id)
        task_ids = [t["id"] for t in tasks]

        assert task1["id"] in task_ids
        assert task2["id"] in task_ids

    def test_list_tasks_filters_by_status(self, project_id: str, cleanup_task: Callable[[str], None]) -> None:
        """Test filtering tasks by status."""
        task1 = task_store.create_task(project_id, "Pending Task")
        task2 = task_store.create_task(project_id, "Running Task")
        cleanup_task(task1["id"])
        cleanup_task(task2["id"])

        # Create spirit record with approved plan (required by G4 enforcement)
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_spirit (task_id, plan_status, complexity)
                VALUES (%s, 'approved', 'SIMPLE')
                """,
                (task2["id"],),
            )
            conn.commit()

        task_store.update_task_status(task2["id"], "running")

        pending = task_store.list_tasks(project_id, status_filter="pending")
        running = task_store.list_tasks(project_id, status_filter="running")

        pending_ids = [t["id"] for t in pending]
        running_ids = [t["id"] for t in running]

        assert task1["id"] in pending_ids
        assert task2["id"] in running_ids
        assert task1["id"] not in running_ids
        assert task2["id"] not in pending_ids

    def test_list_tasks_respects_limit_offset(self, project_id: str, cleanup_task: Callable[[str], None]) -> None:
        """Test pagination with limit and offset."""
        tasks = []
        for i in range(5):
            t = task_store.create_task(project_id, f"Task {i}")
            cleanup_task(t["id"])
            tasks.append(t)

        # List with limit
        limited = task_store.list_tasks(project_id, limit=2)
        assert len(limited) == 2

        # List with offset
        offset = task_store.list_tasks(project_id, limit=2, offset=2)
        assert len(offset) == 2

        # Verify no overlap
        limited_ids = {t["id"] for t in limited}
        offset_ids = {t["id"] for t in offset}
        assert len(limited_ids & offset_ids) == 0


class TestDeleteTask:
    """Tests for delete_task function."""

    def test_delete_task_archives_snapshot_and_hides_live_task(self, project_id: str) -> None:
        """Deleting a task should preserve an archived snapshot for postmortems."""
        task = task_store.create_task(project_id, "To Delete")
        task_id = task["id"]
        subtask_store.create_subtask(task_id, "1.1", "Preserve subtask context", 1)

        result = task_store.delete_task(task_id)
        assert result

        retrieved = task_store.get_task(task_id)
        assert retrieved is None

        archived = task_store.get_deleted_task_context(task_id)
        assert archived is not None
        assert archived["task"]["id"] == task_id
        assert archived["task"]["title"] == "To Delete"
        assert archived["task"]["archived"] is True
        assert archived["task"]["deletion_source"] == "storage:delete_task"
        assert archived["subtasks"][0]["subtask_id"] == "1.1"
        assert archived["subtasks"][0]["description"] == "Preserve subtask context"

    def test_delete_task_nonexistent_returns_false(self) -> None:
        """Test deleting nonexistent task returns False."""
        result = task_store.delete_task("nonexistent-id")
        assert not result
        assert task_store.get_deleted_task_context("nonexistent-id") is None


class TestPurgeTerminalTasks:
    """Tests for purge_terminal_tasks function."""

    def test_purge_deletes_cancelled_tasks(self, project_id: str) -> None:
        task = task_store.create_task(project_id, "To Cancel")
        task_store.update_task_status(task["id"], "cancelled")

        result = task_store.purge_terminal_tasks()

        assert result["cancelled"] >= 1
        assert task_store.get_task(task["id"]) is None
        archived = task_store.get_deleted_task_context(task["id"])
        assert archived is not None
        assert archived["task"]["title"] == "To Cancel"
        assert archived["task"]["deletion_source"] == "storage:purge_terminal_tasks"

    def test_purge_preserves_pending_tasks(self, project_id: str, cleanup_task: Callable[[str], None]) -> None:
        task = task_store.create_task(project_id, "Still Pending")
        cleanup_task(task["id"])

        task_store.purge_terminal_tasks()

        assert task_store.get_task(task["id"]) is not None

    def test_purge_preserves_recent_completed_tasks(self, project_id: str, cleanup_task: Callable[[str], None]) -> None:
        task = task_store.create_task(project_id, "Just Completed")
        task_store.update_task_status(task["id"], "running")
        task_store.update_task_status(task["id"], "completed")
        cleanup_task(task["id"])

        task_store.purge_terminal_tasks(completed_max_age_days=30)

        # Recently completed — should NOT be purged
        assert task_store.get_task(task["id"]) is not None


class TestShortTaskIdResolution:
    def test_get_task_accepts_short_suffix(self, project_id: str) -> None:
        task = task_store.create_task(project_id, "Short id lookup")

        retrieved = task_store.get_task(task["id"].removeprefix("task-"))

        assert retrieved is not None
        assert retrieved["id"] == task["id"]

    def test_update_task_status_accepts_short_suffix(self, project_id: str) -> None:
        task = task_store.create_task(project_id, "Short id status")

        updated = task_store.update_task_status(task["id"].removeprefix("task-"), "running")

        assert updated is not None
        assert updated["id"] == task["id"]
        assert updated["status"] == "running"
