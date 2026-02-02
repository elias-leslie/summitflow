"""Unit tests for tasks storage layer."""

import pytest

from app.storage import tasks as task_store
from app.storage.connection import get_connection


@pytest.fixture
def project_id(ensure_test_project):
    """Use test project from conftest."""
    return ensure_test_project


@pytest.fixture
def test_task(project_id, cleanup_task):
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
            INSERT INTO task_spirit (task_id, objective, plan_status, complexity)
            VALUES (%s, 'Test objective', 'approved', 'SIMPLE')
            ON CONFLICT (task_id) DO UPDATE SET plan_status = 'approved'
            """,
            (task["id"],),
        )
        conn.commit()

    return task


class TestCreateTask:
    """Tests for create_task function."""

    def test_create_task_generates_valid_id(self, project_id, cleanup_task):
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

    def test_create_task_with_custom_id(self, project_id, cleanup_task):
        """Test creating task with custom ID."""
        custom_id = "task-custom-123"
        task = task_store.create_task(
            project_id=project_id,
            title="Custom ID Task",
            task_id=custom_id,
        )
        cleanup_task(task["id"])

        assert task["id"] == custom_id

    def test_create_task_with_all_fields(self, project_id, cleanup_task):
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

    def test_status_pending_to_running(self, test_task):
        """Test transition from pending to running sets started_at."""
        result = task_store.update_task_status(test_task["id"], "running")

        assert result is not None
        assert result["status"] == "running"
        assert result["started_at"] is not None

    def test_status_running_to_completed(self, test_task):
        """Test transition from running to completed sets completed_at."""
        task_store.update_task_status(test_task["id"], "running")
        # QA signoff required before completing (per ac-1050/ac-1051)
        task_store.update_task(test_task["id"], qa_status="skipped")
        result = task_store.update_task_status(test_task["id"], "completed")

        assert result["status"] == "completed"
        assert result["completed_at"] is not None

    def test_status_running_to_failed_with_error(self, test_task):
        """Test transition to failed with error message."""
        task_store.update_task_status(test_task["id"], "running")
        result = task_store.update_task_status(
            test_task["id"], "failed", error_message="Test error"
        )

        assert result["status"] == "failed"
        assert result["error_message"] == "Test error"
        assert result["completed_at"] is not None

    def test_status_paused(self, test_task):
        """Test transition to paused."""
        task_store.update_task_status(test_task["id"], "running")
        result = task_store.update_task_status(test_task["id"], "paused")

        assert result["status"] == "paused"

    def test_invalid_status_raises_error(self, test_task):
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            task_store.update_task_status(test_task["id"], "invalid_status")


class TestListTasks:
    """Tests for list_tasks function."""

    def test_list_tasks_returns_all(self, project_id, cleanup_task):
        """Test listing all tasks for a project."""
        task1 = task_store.create_task(project_id, "Task 1")
        task2 = task_store.create_task(project_id, "Task 2")
        cleanup_task(task1["id"])
        cleanup_task(task2["id"])

        tasks = task_store.list_tasks(project_id)
        task_ids = [t["id"] for t in tasks]

        assert task1["id"] in task_ids
        assert task2["id"] in task_ids

    def test_list_tasks_filters_by_status(self, project_id, cleanup_task):
        """Test filtering tasks by status."""
        task1 = task_store.create_task(project_id, "Pending Task")
        task2 = task_store.create_task(project_id, "Running Task")
        cleanup_task(task1["id"])
        cleanup_task(task2["id"])

        # Create spirit record with approved plan (required by G4 enforcement)
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_spirit (task_id, objective, plan_status, complexity)
                VALUES (%s, 'Test objective', 'approved', 'SIMPLE')
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

    def test_list_tasks_respects_limit_offset(self, project_id, cleanup_task):
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

    def test_delete_task_removes_task(self, project_id):
        """Test that delete_task removes the task."""
        task = task_store.create_task(project_id, "To Delete")
        task_id = task["id"]

        result = task_store.delete_task(task_id)
        assert result is True

        # Verify deleted
        retrieved = task_store.get_task(task_id)
        assert retrieved is None

    def test_delete_task_nonexistent_returns_false(self):
        """Test deleting nonexistent task returns False."""
        result = task_store.delete_task("nonexistent-id")
        assert result is False
