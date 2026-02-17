"""Unit tests for subtasks storage layer."""

from unittest.mock import patch

import pytest

from app.storage import steps as step_store
from app.storage import subtasks as subtask_store
from app.storage.subtasks import SubtaskGateError


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

        # Steps should be populated from normalized table (create_subtask returns "steps" key)
        assert "steps" in subtask
        assert len(subtask["steps"]) == 3
        assert subtask["steps"][0]["description"] == "Step 1"
        assert subtask["steps"][1]["description"] == "Step 2"
        assert subtask["steps"][2]["description"] == "Step 3"

        # Steps should also be retrievable via step storage
        steps_from_storage = step_store.get_steps_for_subtask(subtask["id"])
        assert len(steps_from_storage) == 3

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
        assert "steps" not in subtasks[0]


class TestUpdateSubtaskPasses:
    """Tests for update_subtask_passes function."""

    @patch("app.storage.steps_updates_passes.run_verify_command")
    def test_update_passes_true(self, mock_verify, test_task):
        """Test marking subtask as passing (with steps)."""
        mock_verify.return_value = ("passed", 0, "ok")
        steps = [{"description": "Step", "verify_command": "rg -q 'ok' file.py"}]
        subtask = subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0, steps=steps)

        # Complete step first
        step_store.update_step_passes(subtask["id"], 1, True)

        # Acknowledge citations (required before completing subtask)
        subtask_store.acknowledge_no_citations(test_task["id"], "1.1")

        updated = subtask_store.update_subtask_passes(test_task["id"], "1.1", True)

        assert updated is not None
        assert updated["passes"] is True
        assert updated["passed_at"] is not None

    @patch("app.storage.steps_updates_passes.run_verify_command")
    def test_update_passes_false(self, mock_verify, test_task):
        """Test marking subtask as not passing."""
        mock_verify.return_value = ("passed", 0, "ok")
        steps = [{"description": "Step", "verify_command": "rg -q 'ok' file.py"}]
        subtask = subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0, steps=steps)

        # Complete step and subtask
        step_store.update_step_passes(subtask["id"], 1, True)
        subtask_store.acknowledge_no_citations(test_task["id"], "1.1")
        subtask_store.update_subtask_passes(test_task["id"], "1.1", True)

        # Now clear pass status
        updated = subtask_store.update_subtask_passes(test_task["id"], "1.1", False)

        assert updated is not None
        assert updated["passes"] is False
        assert updated["passed_at"] is None

    @patch("app.storage.steps_updates_passes.run_verify_command")
    def test_update_passes_toggle(self, mock_verify, test_task):
        """Test toggling pass status."""
        mock_verify.return_value = ("passed", 0, "ok")
        steps = [{"description": "Step", "verify_command": "rg -q 'ok' file.py"}]
        subtask = subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0, steps=steps)

        # Complete step
        step_store.update_step_passes(subtask["id"], 1, True)

        # Acknowledge citations before first pass
        subtask_store.acknowledge_no_citations(test_task["id"], "1.1")

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
        """Test updating non-existent subtask returns None (checked before gate)."""
        # For non-existent subtask, we set passes=False to skip gate check
        result = subtask_store.update_subtask_passes(test_task["id"], "99.99", False)

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

        # Verify steps populated directly in returned subtasks
        assert "steps_from_table" in created[0]
        assert len(created[0]["steps_from_table"]) == 3
        assert created[0]["steps_from_table"][0]["description"] == "Step A"
        assert created[0]["steps_from_table"][1]["description"] == "Step B"
        assert created[0]["steps_from_table"][2]["description"] == "Step C"
        assert created[0]["steps_from_table"][0]["step_number"] == 1
        assert created[0]["steps_from_table"][1]["step_number"] == 2
        assert created[0]["steps_from_table"][2]["step_number"] == 3

        assert "steps_from_table" in created[1]
        assert len(created[1]["steps_from_table"]) == 2
        assert created[1]["steps_from_table"][0]["description"] == "Step X"
        assert created[1]["steps_from_table"][1]["description"] == "Step Y"

    def test_bulk_create_without_steps(self, test_task):
        """Test bulk creating subtasks without steps still works."""
        subtasks_data = [
            {"subtask_id": "1.1", "description": "No steps subtask"},
        ]

        created = subtask_store.bulk_create_subtasks(test_task["id"], subtasks_data)

        assert len(created) == 1
        # No steps key when none provided
        assert "steps" not in created[0]

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

    @patch("app.storage.steps_updates_passes.run_verify_command")
    def test_summary_partial(self, mock_verify, test_task):
        """Test summary with partial completion."""
        mock_verify.return_value = ("passed", 0, "ok")
        steps = [{"description": "Step", "verify_command": "rg -q 'ok' file.py"}]

        subtask1 = subtask_store.create_subtask(test_task["id"], "1.1", "First", 0, steps=steps)
        subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1, steps=steps)
        subtask_store.create_subtask(test_task["id"], "2.1", "Third", 2, steps=steps)

        # Complete step and subtask for first one only
        step_store.update_step_passes(subtask1["id"], 1, True)
        subtask_store.acknowledge_no_citations(test_task["id"], "1.1")
        subtask_store.update_subtask_passes(test_task["id"], "1.1", True)

        summary = subtask_store.get_subtask_summary(test_task["id"])

        assert summary["total"] == 3
        assert summary["completed"] == 1
        assert summary["next_subtask_id"] == "1.2"  # Next incomplete
        assert abs(summary["progress_percent"] - 33.3) < 0.1

    @patch("app.storage.steps_updates_passes.run_verify_command")
    def test_summary_all_complete(self, mock_verify, test_task):
        """Test summary with all complete (subtasks with steps verified)."""
        mock_verify.return_value = ("passed", 0, "ok")

        # Create subtasks with steps (required for completion)
        steps = [{"description": "Step", "verify_command": "rg -q 'ok' file.py"}]
        subtask1 = subtask_store.create_subtask(test_task["id"], "1.1", "First", 0, steps=steps)
        subtask2 = subtask_store.create_subtask(test_task["id"], "1.2", "Second", 1, steps=steps)

        # Complete all steps first
        step_store.update_step_passes(subtask1["id"], 1, True)
        step_store.update_step_passes(subtask2["id"], 1, True)

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


class TestSubtaskGates:
    """Tests for subtask step completion gate.

    Note: Strict step verification - gate blocks if ANY steps are incomplete.
    No force param - no bypass available.
    """

    def test_subtask_gate_blocks_incomplete_steps(self, test_task):
        """Subtask pass blocked when steps are incomplete."""
        subtask_store.create_subtask(
            test_task["id"], "1.1", "Test subtask", 0, steps=["Step 1", "Step 2"]
        )

        # Gate blocks - incomplete steps must be completed first
        with pytest.raises(SubtaskGateError, match=r"steps.*are not complete"):
            subtask_store.update_subtask_passes(test_task["id"], "1.1", True)

    @patch("app.storage.steps_updates_passes.run_verify_command")
    def test_subtask_gate_allows_all_steps_complete(self, mock_verify, test_task):
        """Can mark subtask as passed when all steps are complete."""
        mock_verify.return_value = ("passed", 0, "ok")
        steps = [
            {"description": "Step 1", "verify_command": "rg -q 'step1' file.py"},
            {"description": "Step 2", "verify_command": "rg -q 'step2' file.py"},
        ]
        subtask = subtask_store.create_subtask(
            test_task["id"], "1.1", "Test subtask", 0, steps=steps
        )

        # Complete all steps
        step_store.update_step_passes(subtask["id"], 1, True)
        step_store.update_step_passes(subtask["id"], 2, True)

        # Acknowledge citations and mark subtask as passed
        subtask_store.acknowledge_no_citations(test_task["id"], "1.1")
        result = subtask_store.update_subtask_passes(test_task["id"], "1.1", True)
        assert result["passes"] is True

    def test_subtask_gate_force_param_removed(self, test_task):
        """Force flag has been removed - no bypass available."""
        subtask_store.create_subtask(
            test_task["id"],
            "1.1",
            "Test subtask",
            0,
            steps=[
                {"description": "Step 1", "verify_command": "rg -q 'step1' file.py"},
                {"description": "Step 2", "verify_command": "rg -q 'step2' file.py"},
            ],
        )

        # force=True should raise TypeError
        with pytest.raises(TypeError, match="unexpected keyword argument 'force'"):
            subtask_store.update_subtask_passes(test_task["id"], "1.1", True, force=True)

    def test_subtask_gate_rejects_empty_steps(self, test_task):
        """Subtask with no steps cannot be marked as passed.

        This gate ensures every subtask has at least one verifiable step.
        """
        subtask_store.create_subtask(test_task["id"], "1.1", "No steps", 0)

        # Gate blocks - no steps means unverifiable work
        with pytest.raises(SubtaskGateError, match="subtask has no steps"):
            subtask_store.update_subtask_passes(test_task["id"], "1.1", True)

    @patch("app.storage.steps_updates_passes.run_verify_command")
    def test_subtask_gate_partial_completion_blocks(self, mock_verify, test_task):
        """Subtask with some steps complete blocks remaining."""
        mock_verify.return_value = ("passed", 0, "ok")
        steps = [
            {"description": "Step 1", "verify_command": "rg -q 'step1' file.py"},
            {"description": "Step 2", "verify_command": "rg -q 'step2' file.py"},
            {"description": "Step 3", "verify_command": "rg -q 'step3' file.py"},
        ]
        subtask = subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0, steps=steps)

        # Complete only step 1
        step_store.update_step_passes(subtask["id"], 1, True)

        # Gate blocks - steps 2 and 3 still incomplete
        with pytest.raises(SubtaskGateError, match=r"steps.*are not complete"):
            subtask_store.update_subtask_passes(test_task["id"], "1.1", True)

    def test_clearing_subtask_has_no_gate(self, test_task):
        """Setting passes=False has no gate check."""
        subtask_store.create_subtask(test_task["id"], "1.1", "Test", 0, steps=["Step 1"])

        # Can clear subtask even with incomplete steps
        result = subtask_store.update_subtask_passes(test_task["id"], "1.1", False)
        assert result["passes"] is False
