"""Unit tests for subtasks storage layer."""

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
    """Create and cleanup a test task for subtask tests."""
    task = task_store.create_task(
        project_id=project_id,
        title="Test Task for Subtasks",
        description="Created by test fixture",
    )

    yield task

    # Cleanup task (cascades to subtasks)
    task_store.delete_task(task["id"])


class TestGenerateSubtaskId:
    """Tests for _generate_subtask_id helper."""

    def test_generate_subtask_id_basic(self):
        """Test basic subtask ID generation."""
        result = subtask_store._generate_subtask_id("task-abc123", "1.1")
        assert result == "task-abc123-1.1"

    def test_generate_subtask_id_multidigit(self):
        """Test subtask ID with multi-digit numbers."""
        result = subtask_store._generate_subtask_id("task-xyz789", "12.34")
        assert result == "task-xyz789-12.34"


class TestCreateSubtask:
    """Tests for create_subtask function."""

    def test_create_subtask_basic(self, test_task):
        """Test creating a basic subtask."""
        subtask = subtask_store.create_subtask(
            task_id=test_task["id"],
            subtask_id="1.1",
            description="First subtask",
            display_order=0,
        )

        assert subtask is not None
        assert subtask["id"] == f"{test_task['id']}-1.1"
        assert subtask["task_id"] == test_task["id"]
        assert subtask["subtask_id"] == "1.1"
        assert subtask["description"] == "First subtask"
        assert subtask["display_order"] == 0
        assert subtask["passes"] is False
        assert subtask["passed_at"] is None

    def test_create_subtask_with_phase(self, test_task):
        """Test creating subtask with phase."""
        subtask = subtask_store.create_subtask(
            task_id=test_task["id"],
            subtask_id="1.1",
            description="Backend subtask",
            display_order=0,
            phase="backend",
        )

        assert subtask["phase"] == "backend"

    def test_create_subtask_with_steps(self, test_task):
        """Test creating subtask with steps creates them in normalized table."""
        steps = ["Step 1", "Step 2", "Step 3"]
        subtask = subtask_store.create_subtask(
            task_id=test_task["id"],
            subtask_id="1.1",
            description="Subtask with steps",
            display_order=0,
            steps=steps,
        )

        # JSONB column is deprecated - should be empty
        assert subtask["steps"] == []

        # Steps should be in normalized table
        steps_from_table = step_store.get_steps_for_subtask(subtask["id"])
        assert len(steps_from_table) == 3
        assert steps_from_table[0]["description"] == "Step 1"
        assert steps_from_table[1]["description"] == "Step 2"
        assert steps_from_table[2]["description"] == "Step 3"

    def test_create_subtask_multiple(self, test_task):
        """Test creating multiple subtasks."""
        subtask1 = subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask2 = subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)
        subtask3 = subtask_store.create_subtask(test_task["id"], "2.1", "Third", 2)

        assert subtask1["subtask_id"] == "1.1"
        assert subtask2["subtask_id"] == "1.2"
        assert subtask3["subtask_id"] == "2.1"


class TestGetSubtask:
    """Tests for get_subtask function."""

    def test_get_subtask_found(self, test_task):
        """Test getting an existing subtask."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test subtask", 0)

        result = subtask_store.get_subtask(test_task["id"], "1.1")

        assert result is not None
        assert result["subtask_id"] == "1.1"
        assert result["description"] == "Test subtask"

    def test_get_subtask_not_found(self, test_task):
        """Test getting non-existent subtask."""
        result = subtask_store.get_subtask(test_task["id"], "99.99")

        assert result is None

    def test_get_subtask_wrong_task(self, test_task):
        """Test getting subtask with wrong task ID."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test subtask", 0)

        result = subtask_store.get_subtask("nonexistent-task", "1.1")

        assert result is None


class TestGetSubtasksForTask:
    """Tests for get_subtasks_for_task function."""

    def test_get_subtasks_empty(self, test_task):
        """Test getting subtasks from task with no subtasks."""
        subtasks = subtask_store.get_subtasks_for_task(test_task["id"])

        assert subtasks == []

    def test_get_subtasks_populated(self, test_task):
        """Test getting subtasks from task with subtasks."""
        subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)

        subtasks = subtask_store.get_subtasks_for_task(test_task["id"])

        assert len(subtasks) == 2
        assert subtasks[0]["subtask_id"] == "1.1"
        assert subtasks[1]["subtask_id"] == "1.2"

    def test_get_subtasks_ordered(self, test_task):
        """Test subtasks are returned ordered by display_order."""
        # Create out of order
        subtask_store.create_subtask(test_task["id"], "2.1", "Third", 2)
        subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)

        subtasks = subtask_store.get_subtasks_for_task(test_task["id"])

        assert [s["subtask_id"] for s in subtasks] == ["1.1", "1.2", "2.1"]

    def test_get_subtasks_with_steps(self, test_task):
        """Test getting subtasks with include_steps=True."""
        subtask = subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0)
        # Add steps to the subtask via steps table
        step_store.bulk_create_steps(subtask["id"], ["Step 1", "Step 2"])

        subtasks = subtask_store.get_subtasks_for_task(test_task["id"], include_steps=True)

        assert len(subtasks) == 1
        assert "steps_from_table" in subtasks[0]
        assert len(subtasks[0]["steps_from_table"]) == 2
        assert "step_summary" in subtasks[0]
        assert subtasks[0]["step_summary"]["total"] == 2

    def test_get_subtasks_without_steps(self, test_task):
        """Test getting subtasks without include_steps."""
        subtask = subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0)
        step_store.bulk_create_steps(subtask["id"], ["Step 1"])

        subtasks = subtask_store.get_subtasks_for_task(test_task["id"], include_steps=False)

        assert len(subtasks) == 1
        assert "steps_from_table" not in subtasks[0]


class TestUpdateSubtaskPasses:
    """Tests for update_subtask_passes function."""

    def test_update_passes_true(self, test_task):
        """Test marking subtask as passing."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0)

        updated = subtask_store.update_subtask_passes(test_task["id"], "1.1", True)

        assert updated is not None
        assert updated["passes"] is True
        assert updated["passed_at"] is not None

    def test_update_passes_false(self, test_task):
        """Test marking subtask as not passing."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0)
        subtask_store.update_subtask_passes(test_task["id"], "1.1", True)

        updated = subtask_store.update_subtask_passes(test_task["id"], "1.1", False)

        assert updated is not None
        assert updated["passes"] is False
        assert updated["passed_at"] is None

    def test_update_passes_toggle(self, test_task):
        """Test toggling pass status."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0)

        # On
        u1 = subtask_store.update_subtask_passes(test_task["id"], "1.1", True)
        assert u1["passes"] is True

        # Off
        u2 = subtask_store.update_subtask_passes(test_task["id"], "1.1", False)
        assert u2["passes"] is False

        # On again
        u3 = subtask_store.update_subtask_passes(test_task["id"], "1.1", True)
        assert u3["passes"] is True

    def test_update_passes_nonexistent(self, test_task):
        """Test updating non-existent subtask."""
        result = subtask_store.update_subtask_passes(test_task["id"], "99.99", True)

        assert result is None


class TestBulkCreateSubtasks:
    """Tests for bulk_create_subtasks function."""

    def test_bulk_create_basic(self, test_task):
        """Test bulk creating subtasks."""
        subtasks_data = [
            {"subtask_id": "1.1", "description": "First"},
            {"subtask_id": "1.2", "description": "Second"},
            {"subtask_id": "2.1", "description": "Third"},
        ]

        created = subtask_store.bulk_create_subtasks(test_task["id"], subtasks_data)

        assert len(created) == 3
        assert created[0]["subtask_id"] == "1.1"
        assert created[1]["subtask_id"] == "1.2"
        assert created[2]["subtask_id"] == "2.1"
        # Auto-assigned display_order
        assert created[0]["display_order"] == 0
        assert created[1]["display_order"] == 1
        assert created[2]["display_order"] == 2

    def test_bulk_create_with_phase(self, test_task):
        """Test bulk creating with phase."""
        subtasks_data = [
            {"subtask_id": "1.1", "description": "Research", "phase": "research"},
            {"subtask_id": "1.2", "description": "Backend", "phase": "backend"},
        ]

        created = subtask_store.bulk_create_subtasks(test_task["id"], subtasks_data)

        assert created[0]["phase"] == "research"
        assert created[1]["phase"] == "backend"

    def test_bulk_create_empty(self, test_task):
        """Test bulk creating with empty list."""
        created = subtask_store.bulk_create_subtasks(test_task["id"], [])

        assert created == []

    def test_bulk_create_with_display_order(self, test_task):
        """Test bulk creating with explicit display_order."""
        subtasks_data = [
            {"subtask_id": "1.1", "description": "First", "display_order": 10},
            {"subtask_id": "1.2", "description": "Second", "display_order": 5},
        ]

        created = subtask_store.bulk_create_subtasks(test_task["id"], subtasks_data)

        assert created[0]["display_order"] == 10
        assert created[1]["display_order"] == 5

    def test_bulk_create_auto_creates_steps_in_normalized_table(self, test_task):
        """Test that bulk_create_subtasks creates step rows in task_subtask_steps table."""
        subtasks_data = [
            {
                "subtask_id": "1.1",
                "description": "First subtask",
                "steps": ["Step A", "Step B", "Step C"],
            },
            {
                "subtask_id": "1.2",
                "description": "Second subtask",
                "steps": ["Step X", "Step Y"],
            },
        ]

        created = subtask_store.bulk_create_subtasks(test_task["id"], subtasks_data)

        assert len(created) == 2

        # Verify steps created in normalized table (not JSONB)
        # JSONB column should be empty since we don't use it
        assert created[0]["steps"] == []
        assert created[1]["steps"] == []

        # Verify steps in task_subtask_steps table
        steps_1_1 = step_store.get_steps_for_subtask(created[0]["id"])
        assert len(steps_1_1) == 3
        assert steps_1_1[0]["description"] == "Step A"
        assert steps_1_1[1]["description"] == "Step B"
        assert steps_1_1[2]["description"] == "Step C"
        assert steps_1_1[0]["step_number"] == 1
        assert steps_1_1[1]["step_number"] == 2
        assert steps_1_1[2]["step_number"] == 3

        steps_1_2 = step_store.get_steps_for_subtask(created[1]["id"])
        assert len(steps_1_2) == 2
        assert steps_1_2[0]["description"] == "Step X"
        assert steps_1_2[1]["description"] == "Step Y"

    def test_bulk_create_without_steps(self, test_task):
        """Test bulk creating subtasks without steps still works."""
        subtasks_data = [
            {"subtask_id": "1.1", "description": "No steps subtask"},
        ]

        created = subtask_store.bulk_create_subtasks(test_task["id"], subtasks_data)

        assert len(created) == 1
        assert created[0]["steps"] == []

        # No steps in normalized table either
        steps = step_store.get_steps_for_subtask(created[0]["id"])
        assert steps == []

    def test_bulk_create_mixed_with_and_without_steps(self, test_task):
        """Test bulk creating subtasks where some have steps and some don't."""
        subtasks_data = [
            {
                "subtask_id": "1.1",
                "description": "With steps",
                "steps": ["Step 1", "Step 2"],
            },
            {
                "subtask_id": "1.2",
                "description": "Without steps",
            },
            {
                "subtask_id": "1.3",
                "description": "With more steps",
                "steps": ["Step A"],
            },
        ]

        created = subtask_store.bulk_create_subtasks(test_task["id"], subtasks_data)

        assert len(created) == 3

        # First subtask has 2 steps
        steps_1_1 = step_store.get_steps_for_subtask(created[0]["id"])
        assert len(steps_1_1) == 2

        # Second subtask has no steps
        steps_1_2 = step_store.get_steps_for_subtask(created[1]["id"])
        assert len(steps_1_2) == 0

        # Third subtask has 1 step
        steps_1_3 = step_store.get_steps_for_subtask(created[2]["id"])
        assert len(steps_1_3) == 1


class TestDeleteSubtasksForTask:
    """Tests for delete_subtasks_for_task function."""

    def test_delete_subtasks_basic(self, test_task):
        """Test deleting all subtasks."""
        subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)
        subtask_store.create_subtask(test_task["id"], "2.1", "Third", 2)

        count = subtask_store.delete_subtasks_for_task(test_task["id"])

        assert count == 3

        # Verify deletion
        subtasks = subtask_store.get_subtasks_for_task(test_task["id"])
        assert subtasks == []

    def test_delete_subtasks_empty(self, test_task):
        """Test deleting from task with no subtasks."""
        count = subtask_store.delete_subtasks_for_task(test_task["id"])

        assert count == 0

    def test_delete_subtasks_nonexistent_task(self):
        """Test deleting from non-existent task."""
        count = subtask_store.delete_subtasks_for_task("nonexistent-task")

        assert count == 0


class TestGetSubtaskSummary:
    """Tests for get_subtask_summary function."""

    def test_summary_empty(self, test_task):
        """Test summary with no subtasks."""
        summary = subtask_store.get_subtask_summary(test_task["id"])

        assert summary["total"] == 0
        assert summary["completed"] == 0
        assert summary["next_subtask_id"] is None
        assert summary["progress_percent"] == 0

    def test_summary_all_incomplete(self, test_task):
        """Test summary with all subtasks incomplete."""
        subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)

        summary = subtask_store.get_subtask_summary(test_task["id"])

        assert summary["total"] == 2
        assert summary["completed"] == 0
        assert summary["next_subtask_id"] == "1.1"
        assert summary["progress_percent"] == 0

    def test_summary_partial(self, test_task):
        """Test summary with partial completion."""
        subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)
        subtask_store.create_subtask(test_task["id"], "2.1", "Third", 2)
        subtask_store.update_subtask_passes(test_task["id"], "1.1", True)

        summary = subtask_store.get_subtask_summary(test_task["id"])

        assert summary["total"] == 3
        assert summary["completed"] == 1
        assert summary["next_subtask_id"] == "1.2"  # Next incomplete
        assert abs(summary["progress_percent"] - 33.3) < 0.1

    def test_summary_all_complete(self, test_task):
        """Test summary with all complete."""
        subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)
        subtask_store.update_subtask_passes(test_task["id"], "1.1", True)
        subtask_store.update_subtask_passes(test_task["id"], "1.2", True)

        summary = subtask_store.get_subtask_summary(test_task["id"])

        assert summary["total"] == 2
        assert summary["completed"] == 2
        assert summary["next_subtask_id"] is None
        assert summary["progress_percent"] == 100.0
