"""Unit tests for tasks storage layer."""

import pytest

from app.storage import tasks as task_store
from app.storage.connection import get_connection


@pytest.fixture
def project_id():
    """Ensure test project exists."""
    project_id = "summitflow"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (id, name, base_url) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (project_id, "SummitFlow", "http://localhost:3001"),
        )
        conn.commit()
    return project_id


@pytest.fixture
def test_task(project_id):
    """Create and cleanup a test task."""
    task = task_store.create_task(
        project_id=project_id,
        title="Test Task for Unit Tests",
        description="Created by test fixture",
    )

    yield task

    # Cleanup
    task_store.delete_task(task["id"])


class TestCreateTask:
    """Tests for create_task function."""

    def test_create_task_generates_valid_id(self, project_id):
        """Test that create_task generates a valid task_id."""
        task = task_store.create_task(
            project_id=project_id,
            title="Test Create",
        )

        try:
            assert task is not None
            assert task["id"].startswith("task-")
            assert len(task["id"]) == 13  # "task-" + 8 hex chars
            assert task["status"] == "pending"
            assert task["project_id"] == project_id
        finally:
            task_store.delete_task(task["id"])

    def test_create_task_with_custom_id(self, project_id):
        """Test creating task with custom ID."""
        custom_id = "task-custom-123"
        task = task_store.create_task(
            project_id=project_id,
            title="Custom ID Task",
            task_id=custom_id,
        )

        try:
            assert task["id"] == custom_id
        finally:
            task_store.delete_task(task["id"])

    def test_create_task_with_all_fields(self, project_id):
        """Test creating task with all optional fields."""
        task = task_store.create_task(
            project_id=project_id,
            title="Full Task",
            description="Full description",
            capability_id=None,  # Optional capability link
        )

        try:
            assert task["title"] == "Full Task"
            assert task["description"] == "Full description"
            assert task["capability_id"] is None
        finally:
            task_store.delete_task(task["id"])


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

    def test_list_tasks_returns_all(self, project_id):
        """Test listing all tasks for a project."""
        # Create multiple tasks
        task1 = task_store.create_task(project_id, "Task 1")
        task2 = task_store.create_task(project_id, "Task 2")

        try:
            tasks = task_store.list_tasks(project_id)
            task_ids = [t["id"] for t in tasks]

            assert task1["id"] in task_ids
            assert task2["id"] in task_ids
        finally:
            task_store.delete_task(task1["id"])
            task_store.delete_task(task2["id"])

    def test_list_tasks_filters_by_status(self, project_id):
        """Test filtering tasks by status."""
        task1 = task_store.create_task(project_id, "Pending Task")
        task2 = task_store.create_task(project_id, "Running Task")
        task_store.update_task_status(task2["id"], "running")

        try:
            pending = task_store.list_tasks(project_id, status_filter="pending")
            running = task_store.list_tasks(project_id, status_filter="running")

            pending_ids = [t["id"] for t in pending]
            running_ids = [t["id"] for t in running]

            assert task1["id"] in pending_ids
            assert task2["id"] in running_ids
            assert task1["id"] not in running_ids
            assert task2["id"] not in pending_ids
        finally:
            task_store.delete_task(task1["id"])
            task_store.delete_task(task2["id"])

    def test_list_tasks_respects_limit_offset(self, project_id):
        """Test pagination with limit and offset."""
        tasks = []
        for i in range(5):
            t = task_store.create_task(project_id, f"Task {i}")
            tasks.append(t)

        try:
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
        finally:
            for t in tasks:
                task_store.delete_task(t["id"])


class TestAppendProgressLog:
    """Tests for append_progress_log function."""

    def test_append_progress_log_adds_entry(self, test_task):
        """Test that append_progress_log adds timestamped entry."""
        result = task_store.append_progress_log(test_task["id"], "Test log entry")

        assert result is not None
        assert "Test log entry" in result["progress_log"]
        assert "]" in result["progress_log"]  # Has timestamp brackets

    def test_append_progress_log_multiple_entries(self, test_task):
        """Test appending multiple log entries."""
        task_store.append_progress_log(test_task["id"], "Entry 1")
        task_store.append_progress_log(test_task["id"], "Entry 2")
        result = task_store.append_progress_log(test_task["id"], "Entry 3")

        assert "Entry 1" in result["progress_log"]
        assert "Entry 2" in result["progress_log"]
        assert "Entry 3" in result["progress_log"]

    def test_append_progress_log_nonexistent_task(self):
        """Test appending to nonexistent task returns None."""
        result = task_store.append_progress_log("nonexistent-id", "Entry")
        assert result is None


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
