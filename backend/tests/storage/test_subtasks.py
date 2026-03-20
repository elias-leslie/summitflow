"""Unit tests for subtasks storage layer."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.storage import subtasks as subtask_store
from app.storage.subtasks_crud import generate_subtask_id as _generate_subtask_id


class TestGenerateSubtaskId:
    """Tests for _generate_subtask_id helper."""

    def test_generate_subtask_id_basic(self) -> None:
        """Test basic subtask ID generation."""
        result = _generate_subtask_id("task-abc123", "1.1")
        assert result == "task-abc123-1.1"

    def test_generate_subtask_id_multidigit(self) -> None:
        """Test subtask ID with multi-digit numbers."""
        result = _generate_subtask_id("task-xyz789", "12.34")
        assert result == "task-xyz789-12.34"


class TestCreateSubtask:
    """Tests for create_subtask function."""

    def test_create_subtask_basic(self, test_task: dict[str, Any]) -> None:
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
        assert not subtask["passes"]
        assert subtask["passed_at"] is None

    def test_create_subtask_with_phase(self, test_task: dict[str, Any]) -> None:
        """Test creating subtask with phase."""
        subtask = subtask_store.create_subtask(
            task_id=test_task["id"],
            subtask_id="1.1",
            description="Backend subtask",
            display_order=0,
            phase="backend",
        )

        assert subtask["phase"] == "backend"

    def test_create_subtask_with_steps_no_crash(self, test_task: dict[str, Any]) -> None:
        """Test creating subtask with steps param doesn't crash (steps layer removed)."""
        steps: list[str | dict[str, Any]] = ["Step 1", "Step 2", "Step 3"]
        subtask = subtask_store.create_subtask(
            task_id=test_task["id"],
            subtask_id="1.1",
            description="Subtask with steps",
            display_order=0,
            steps=steps,
        )

        # Subtask created successfully — steps param accepted but no-op
        assert subtask is not None
        assert subtask["subtask_id"] == "1.1"

    def test_create_subtask_multiple(self, test_task: dict[str, Any]) -> None:
        """Test creating multiple subtasks."""
        subtask1 = subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask2 = subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)
        subtask3 = subtask_store.create_subtask(test_task["id"], "2.1", "Third", 2)

        assert subtask1["subtask_id"] == "1.1"
        assert subtask2["subtask_id"] == "1.2"
        assert subtask3["subtask_id"] == "2.1"


class TestGetSubtask:
    """Tests for get_subtask function."""

    def test_get_subtask_found(self, test_task: dict[str, Any]) -> None:
        """Test getting an existing subtask."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test subtask", 0)

        result = subtask_store.get_subtask(test_task["id"], "1.1")

        assert result is not None
        assert result["subtask_id"] == "1.1"
        assert result["description"] == "Test subtask"

    def test_get_subtask_not_found(self, test_task: dict[str, Any]) -> None:
        """Test getting non-existent subtask."""
        result = subtask_store.get_subtask(test_task["id"], "99.99")

        assert result is None

    def test_get_subtask_wrong_task(self, test_task: dict[str, Any]) -> None:
        """Test getting subtask with wrong task ID."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test subtask", 0)

        result = subtask_store.get_subtask("nonexistent-task", "1.1")

        assert result is None


class TestGetSubtasksForTask:
    """Tests for get_subtasks_for_task function."""

    def test_get_subtasks_empty(self, test_task: dict[str, Any]) -> None:
        """Test getting subtasks from task with no subtasks."""
        subtasks = subtask_store.get_subtasks_for_task(test_task["id"])

        assert subtasks == []

    def test_get_subtasks_populated(self, test_task: dict[str, Any]) -> None:
        """Test getting subtasks from task with subtasks."""
        subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)

        subtasks = subtask_store.get_subtasks_for_task(test_task["id"])

        assert len(subtasks) == 2
        assert subtasks[0]["subtask_id"] == "1.1"
        assert subtasks[1]["subtask_id"] == "1.2"

    def test_get_subtasks_ordered(self, test_task: dict[str, Any]) -> None:
        """Test subtasks are returned ordered by display_order."""
        # Create out of order
        subtask_store.create_subtask(test_task["id"], "2.1", "Third", 2)
        subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)

        subtasks = subtask_store.get_subtasks_for_task(test_task["id"])

        assert [s["subtask_id"] for s in subtasks] == ["1.1", "1.2", "2.1"]

    def test_get_subtasks_with_include_steps(self, test_task: dict[str, Any]) -> None:
        """Test getting subtasks with include_steps=True returns empty step data (steps layer removed)."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0)

        subtasks = subtask_store.get_subtasks_for_task(test_task["id"], include_steps=True)

        assert len(subtasks) == 1
        assert subtasks[0]["steps_from_table"] == []
        assert subtasks[0]["step_summary"] == {"total": 0, "completed": 0}

    @patch("app.storage.task_spirit.get_task_spirit")
    def test_get_subtasks_with_include_steps_uses_plan_context_guidance(
        self,
        mock_get_spirit: MagicMock,
        test_task: dict[str, Any],
    ) -> None:
        """Plan-context subtasks should surface step guidance when step rows do not exist."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0)
        mock_get_spirit.return_value = {
            "context": {
                "subtasks": [
                    {
                        "subtask_id": "1.1",
                        "description": "Test",
                        "steps": [
                            {"step_number": 1, "description": "Keep behavior stable", "passes": False},
                            {"step_number": 2, "description": "Run dt -q -d", "passes": False},
                        ],
                    }
                ]
            }
        }

        subtasks = subtask_store.get_subtasks_for_task(test_task["id"], include_steps=True)

        assert len(subtasks) == 1
        assert subtasks[0]["steps_from_table"] == []
        assert subtasks[0]["steps_source"] == "plan_context"
        assert subtasks[0]["steps"] == [
            {"step_number": 1, "description": "Keep behavior stable", "passes": False},
            {"step_number": 2, "description": "Run dt -q -d", "passes": False},
        ]
        assert subtasks[0]["step_summary"] == {"total": 2, "completed": 0}


class TestUpdateSubtaskPasses:
    """Tests for update_subtask_passes function."""

    def test_update_passes_true(self, test_task: dict[str, Any]) -> None:
        """Test marking subtask as passing (citations acknowledged)."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0)

        # Acknowledge citations (required before completing subtask)
        subtask_store.acknowledge_no_citations(test_task["id"], "1.1")

        updated = subtask_store.update_subtask_passes(test_task["id"], "1.1", True)

        assert updated is not None
        assert updated["passes"]
        assert updated["passed_at"] is not None

    def test_update_passes_false(self, test_task: dict[str, Any]) -> None:
        """Test marking subtask as not passing."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0)

        # Complete and then clear
        subtask_store.acknowledge_no_citations(test_task["id"], "1.1")
        subtask_store.update_subtask_passes(test_task["id"], "1.1", True)

        updated = subtask_store.update_subtask_passes(test_task["id"], "1.1", False)

        assert updated is not None
        assert not updated["passes"]
        assert updated["passed_at"] is None

    def test_update_passes_toggle(self, test_task: dict[str, Any]) -> None:
        """Test toggling pass status."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0)

        # Acknowledge citations before first pass
        subtask_store.acknowledge_no_citations(test_task["id"], "1.1")

        # On
        u1 = subtask_store.update_subtask_passes(test_task["id"], "1.1", True)
        assert u1 is not None
        assert u1["passes"]

        # Off
        u2 = subtask_store.update_subtask_passes(test_task["id"], "1.1", False)
        assert u2 is not None
        assert not u2["passes"]

        # On again
        u3 = subtask_store.update_subtask_passes(test_task["id"], "1.1", True)
        assert u3 is not None
        assert u3["passes"]

    def test_update_passes_nonexistent(self, test_task: dict[str, Any]) -> None:
        """Test updating non-existent subtask returns None."""
        result = subtask_store.update_subtask_passes(test_task["id"], "99.99", False)

        assert result is None


class TestBulkCreateSubtasks:
    """Tests for bulk_create_subtasks function."""

    def test_bulk_create_basic(self, test_task: dict[str, Any]) -> None:
        """Test bulk creating subtasks."""
        subtasks_data: list[dict[str, Any]] = [
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

    def test_bulk_create_with_phase(self, test_task: dict[str, Any]) -> None:
        """Test bulk creating with phase."""
        subtasks_data: list[dict[str, Any]] = [
            {"subtask_id": "1.1", "description": "Research", "phase": "research"},
            {"subtask_id": "1.2", "description": "Backend", "phase": "backend"},
        ]

        created = subtask_store.bulk_create_subtasks(test_task["id"], subtasks_data)

        assert created[0]["phase"] == "research"
        assert created[1]["phase"] == "backend"

    def test_bulk_create_empty(self, test_task: dict[str, Any]) -> None:
        """Test bulk creating with empty list."""
        created = subtask_store.bulk_create_subtasks(test_task["id"], [])

        assert created == []

    def test_bulk_create_with_display_order(self, test_task: dict[str, Any]) -> None:
        """Test bulk creating with explicit display_order."""
        subtasks_data: list[dict[str, Any]] = [
            {"subtask_id": "1.1", "description": "First", "display_order": 10},
            {"subtask_id": "1.2", "description": "Second", "display_order": 5},
        ]

        created = subtask_store.bulk_create_subtasks(test_task["id"], subtasks_data)

        assert created[0]["display_order"] == 10
        assert created[1]["display_order"] == 5

    def test_bulk_create_without_steps(self, test_task: dict[str, Any]) -> None:
        """Test bulk creating subtasks without steps still works."""
        subtasks_data: list[dict[str, Any]] = [
            {"subtask_id": "1.1", "description": "No steps subtask"},
        ]

        created = subtask_store.bulk_create_subtasks(test_task["id"], subtasks_data)

        assert len(created) == 1


class TestDeleteSubtasksForTask:
    """Tests for delete_subtasks_for_task function."""

    def test_delete_subtasks_basic(self, test_task: dict[str, Any]) -> None:
        """Test deleting all subtasks."""
        subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)
        subtask_store.create_subtask(test_task["id"], "2.1", "Third", 2)

        count = subtask_store.delete_subtasks_for_task(test_task["id"])

        assert count == 3

        # Verify deletion
        subtasks = subtask_store.get_subtasks_for_task(test_task["id"])
        assert subtasks == []

    def test_delete_subtasks_empty(self, test_task: dict[str, Any]) -> None:
        """Test deleting from task with no subtasks."""
        count = subtask_store.delete_subtasks_for_task(test_task["id"])

        assert count == 0

    def test_delete_subtasks_nonexistent_task(self) -> None:
        """Test deleting from non-existent task."""
        count = subtask_store.delete_subtasks_for_task("nonexistent-task")

        assert count == 0


class TestGetSubtaskSummary:
    """Tests for get_subtask_summary function."""

    def test_summary_empty(self, test_task: dict[str, Any]) -> None:
        """Test summary with no subtasks."""
        summary = subtask_store.get_subtask_summary(test_task["id"])

        assert summary["total"] == 0
        assert summary["completed"] == 0
        assert summary["next_subtask_id"] is None
        assert summary["progress_percent"] == 0

    def test_summary_all_incomplete(self, test_task: dict[str, Any]) -> None:
        """Test summary with all subtasks incomplete."""
        subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)

        summary = subtask_store.get_subtask_summary(test_task["id"])

        assert summary["total"] == 2
        assert summary["completed"] == 0
        assert summary["next_subtask_id"] == "1.1"
        assert summary["progress_percent"] == 0

    def test_summary_partial(self, test_task: dict[str, Any]) -> None:
        """Test summary with partial completion."""
        subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)
        subtask_store.create_subtask(test_task["id"], "2.1", "Third", 2)

        # Complete first subtask (citations only — steps layer removed)
        subtask_store.acknowledge_no_citations(test_task["id"], "1.1")
        subtask_store.update_subtask_passes(test_task["id"], "1.1", True)

        summary = subtask_store.get_subtask_summary(test_task["id"])

        assert summary["total"] == 3
        assert summary["completed"] == 1
        assert summary["next_subtask_id"] == "1.2"  # Next incomplete
        assert abs(summary["progress_percent"] - 33.3) < 0.1

    def test_summary_all_complete(self, test_task: dict[str, Any]) -> None:
        """Test summary with all complete."""
        subtask_store.create_subtask(test_task["id"], "1.1", "First", 0)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1)

        # Acknowledge citations and mark subtasks complete
        subtask_store.acknowledge_no_citations(test_task["id"], "1.1")
        subtask_store.update_subtask_passes(test_task["id"], "1.1", True)
        subtask_store.acknowledge_no_citations(test_task["id"], "1.2")
        subtask_store.update_subtask_passes(test_task["id"], "1.2", True)

        summary = subtask_store.get_subtask_summary(test_task["id"])

        assert summary["total"] == 2
        assert summary["completed"] == 2
        assert summary["next_subtask_id"] is None
        assert summary["progress_percent"] == 100.0
