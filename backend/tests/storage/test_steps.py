"""Unit tests for steps storage layer."""

import pytest
from app.storage import steps as step_store
from app.storage import subtasks as subtask_store
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
    """Create and cleanup a test task for step tests."""
    task = task_store.create_task(
        project_id=project_id,
        title="Test Task for Steps",
        description="Created by test fixture",
    )

    yield task

    # Cleanup task (cascades to subtasks and steps)
    task_store.delete_task(task["id"])


@pytest.fixture
def test_subtask(test_task):
    """Create and cleanup a test subtask for step tests."""
    subtask = subtask_store.create_subtask(
        task_id=test_task["id"],
        subtask_id="1.1",
        description="Test subtask for steps",
        display_order=0,
        phase="test",
    )

    yield subtask

    # Cleanup happens via task cascade


class TestCreateStep:
    """Tests for create_step function."""

    def test_create_step_basic(self, test_subtask):
        """Test creating a basic step."""
        step = step_store.create_step(
            subtask_id=test_subtask["id"],
            step_number=1,
            description="First test step",
        )

        assert step is not None
        assert step["subtask_id"] == test_subtask["id"]
        assert step["step_number"] == 1
        assert step["description"] == "First test step"
        assert step["passes"] is False
        assert step["passed_at"] is None
        assert step["created_at"] is not None

    def test_create_step_multiple(self, test_subtask):
        """Test creating multiple steps with sequential numbers."""
        step1 = step_store.create_step(test_subtask["id"], 1, "Step one")
        step2 = step_store.create_step(test_subtask["id"], 2, "Step two")
        step3 = step_store.create_step(test_subtask["id"], 3, "Step three")

        assert step1["step_number"] == 1
        assert step2["step_number"] == 2
        assert step3["step_number"] == 3


class TestGetStepsForSubtask:
    """Tests for get_steps_for_subtask function."""

    def test_get_steps_empty(self, test_subtask):
        """Test getting steps from subtask with no steps."""
        steps = step_store.get_steps_for_subtask(test_subtask["id"])

        assert steps == []

    def test_get_steps_populated(self, test_subtask):
        """Test getting steps from subtask with steps."""
        step_store.create_step(test_subtask["id"], 1, "First step")
        step_store.create_step(test_subtask["id"], 2, "Second step")

        steps = step_store.get_steps_for_subtask(test_subtask["id"])

        assert len(steps) == 2
        assert steps[0]["step_number"] == 1
        assert steps[1]["step_number"] == 2

    def test_get_steps_ordered(self, test_subtask):
        """Test that steps are returned in order by step_number."""
        # Create out of order
        step_store.create_step(test_subtask["id"], 3, "Third")
        step_store.create_step(test_subtask["id"], 1, "First")
        step_store.create_step(test_subtask["id"], 2, "Second")

        steps = step_store.get_steps_for_subtask(test_subtask["id"])

        assert len(steps) == 3
        assert [s["step_number"] for s in steps] == [1, 2, 3]

    def test_get_steps_nonexistent_subtask(self):
        """Test getting steps for non-existent subtask returns empty list."""
        steps = step_store.get_steps_for_subtask("nonexistent-subtask-id")

        assert steps == []


class TestUpdateStepPasses:
    """Tests for update_step_passes function."""

    def test_update_step_passes_true(self, test_subtask):
        """Test marking a step as passing."""
        step_store.create_step(test_subtask["id"], 1, "Test step")

        updated = step_store.update_step_passes(test_subtask["id"], 1, True)

        assert updated is not None
        assert updated["passes"] is True
        assert updated["passed_at"] is not None

    def test_update_step_passes_false(self, test_subtask):
        """Test marking a step as not passing (resetting)."""
        step_store.create_step(test_subtask["id"], 1, "Test step")
        step_store.update_step_passes(test_subtask["id"], 1, True)

        updated = step_store.update_step_passes(test_subtask["id"], 1, False)

        assert updated is not None
        assert updated["passes"] is False
        assert updated["passed_at"] is None

    def test_update_step_passes_toggle(self, test_subtask):
        """Test toggling step pass status multiple times."""
        step_store.create_step(test_subtask["id"], 1, "Test step")

        # Toggle on
        updated1 = step_store.update_step_passes(test_subtask["id"], 1, True)
        assert updated1["passes"] is True

        # Toggle off
        updated2 = step_store.update_step_passes(test_subtask["id"], 1, False)
        assert updated2["passes"] is False

        # Toggle on again
        updated3 = step_store.update_step_passes(test_subtask["id"], 1, True)
        assert updated3["passes"] is True

    def test_update_step_passes_nonexistent(self, test_subtask):
        """Test updating non-existent step returns None."""
        result = step_store.update_step_passes(test_subtask["id"], 999, True)

        assert result is None


class TestBulkCreateSteps:
    """Tests for bulk_create_steps function."""

    def test_bulk_create_steps_basic(self, test_subtask):
        """Test bulk creating multiple steps."""
        descriptions = ["Step 1", "Step 2", "Step 3"]

        created = step_store.bulk_create_steps(test_subtask["id"], descriptions)

        assert len(created) == 3
        assert created[0]["step_number"] == 1
        assert created[1]["step_number"] == 2
        assert created[2]["step_number"] == 3
        assert created[0]["description"] == "Step 1"

    def test_bulk_create_steps_empty(self, test_subtask):
        """Test bulk creating with empty list."""
        created = step_store.bulk_create_steps(test_subtask["id"], [])

        assert created == []

    def test_bulk_create_steps_single(self, test_subtask):
        """Test bulk creating single step."""
        created = step_store.bulk_create_steps(test_subtask["id"], ["Only step"])

        assert len(created) == 1
        assert created[0]["step_number"] == 1
        assert created[0]["description"] == "Only step"


class TestDeleteStepsForSubtask:
    """Tests for delete_steps_for_subtask function."""

    def test_delete_steps_basic(self, test_subtask):
        """Test deleting all steps for a subtask."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3"])

        count = step_store.delete_steps_for_subtask(test_subtask["id"])

        assert count == 3

        # Verify deletion
        steps = step_store.get_steps_for_subtask(test_subtask["id"])
        assert steps == []

    def test_delete_steps_empty(self, test_subtask):
        """Test deleting from subtask with no steps."""
        count = step_store.delete_steps_for_subtask(test_subtask["id"])

        assert count == 0

    def test_delete_steps_nonexistent_subtask(self):
        """Test deleting steps for non-existent subtask."""
        count = step_store.delete_steps_for_subtask("nonexistent-subtask")

        assert count == 0


class TestGetStepSummary:
    """Tests for get_step_summary function."""

    def test_step_summary_empty(self, test_subtask):
        """Test summary with no steps."""
        summary = step_store.get_step_summary(test_subtask["id"])

        assert summary["total"] == 0
        assert summary["completed"] == 0
        assert summary["progress_percent"] == 0

    def test_step_summary_all_incomplete(self, test_subtask):
        """Test summary with all steps incomplete."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3"])

        summary = step_store.get_step_summary(test_subtask["id"])

        assert summary["total"] == 3
        assert summary["completed"] == 0
        assert summary["progress_percent"] == 0

    def test_step_summary_partial(self, test_subtask):
        """Test summary with partial completion."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3", "Step 4"])
        step_store.update_step_passes(test_subtask["id"], 1, True)
        step_store.update_step_passes(test_subtask["id"], 2, True)

        summary = step_store.get_step_summary(test_subtask["id"])

        assert summary["total"] == 4
        assert summary["completed"] == 2
        assert summary["progress_percent"] == 50.0

    def test_step_summary_all_complete(self, test_subtask):
        """Test summary with all steps complete."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2"])
        step_store.update_step_passes(test_subtask["id"], 1, True)
        step_store.update_step_passes(test_subtask["id"], 2, True)

        summary = step_store.get_step_summary(test_subtask["id"])

        assert summary["total"] == 2
        assert summary["completed"] == 2
        assert summary["progress_percent"] == 100.0

    def test_step_summary_nonexistent_subtask(self):
        """Test summary for non-existent subtask."""
        summary = step_store.get_step_summary("nonexistent-subtask")

        assert summary["total"] == 0
        assert summary["completed"] == 0
        assert summary["progress_percent"] == 0
