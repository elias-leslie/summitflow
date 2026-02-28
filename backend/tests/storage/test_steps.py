"""Unit tests for steps storage layer."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from app.storage import steps as step_store
from app.storage import subtasks as subtask_store


@pytest.fixture
def test_subtask(test_task: dict[str, Any]) -> Generator[dict[str, Any]]:
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

    def test_create_step_basic(self, test_subtask: dict[str, Any]) -> None:
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

    def test_create_step_multiple(self, test_subtask: dict[str, Any]) -> None:
        """Test creating multiple steps with sequential numbers."""
        step1 = step_store.create_step(test_subtask["id"], 1, "Step one")
        step2 = step_store.create_step(test_subtask["id"], 2, "Step two")
        step3 = step_store.create_step(test_subtask["id"], 3, "Step three")

        assert step1["step_number"] == 1
        assert step2["step_number"] == 2
        assert step3["step_number"] == 3


class TestGetStepsForSubtask:
    """Tests for get_steps_for_subtask function."""

    def test_get_steps_empty(self, test_subtask: dict[str, Any]) -> None:
        """Test getting steps from subtask with no steps."""
        steps = step_store.get_steps_for_subtask(test_subtask["id"])

        assert steps == []

    def test_get_steps_populated(self, test_subtask: dict[str, Any]) -> None:
        """Test getting steps from subtask with steps."""
        step_store.create_step(test_subtask["id"], 1, "First step")
        step_store.create_step(test_subtask["id"], 2, "Second step")

        steps = step_store.get_steps_for_subtask(test_subtask["id"])

        assert len(steps) == 2
        assert steps[0]["step_number"] == 1
        assert steps[1]["step_number"] == 2

    def test_get_steps_ordered(self, test_subtask: dict[str, Any]) -> None:
        """Test that steps are returned in order by step_number."""
        # Create out of order
        step_store.create_step(test_subtask["id"], 3, "Third")
        step_store.create_step(test_subtask["id"], 1, "First")
        step_store.create_step(test_subtask["id"], 2, "Second")

        steps = step_store.get_steps_for_subtask(test_subtask["id"])

        assert len(steps) == 3
        assert [s["step_number"] for s in steps] == [1, 2, 3]

    def test_get_steps_nonexistent_subtask(self) -> None:
        """Test getting steps for non-existent subtask returns empty list."""
        steps = step_store.get_steps_for_subtask("nonexistent-subtask-id")

        assert steps == []


class TestUpdateStepPasses:
    """Tests for update_step_passes function.

    Steps are now simple progress trackers that get auto-marked passed.
    No verification is involved.
    """

    def test_update_step_passes_true(self, test_subtask: dict[str, Any]) -> None:
        """Test marking a step as passing."""
        step_store.create_step(test_subtask["id"], 1, "Test step")

        updated = step_store.update_step_passes(test_subtask["id"], 1, True)

        assert updated is not None
        assert updated["passes"] is True
        assert updated["passed_at"] is not None

    def test_update_step_passes_false(self, test_subtask: dict[str, Any]) -> None:
        """Test marking a step as not passing (resetting)."""
        step_store.create_step(test_subtask["id"], 1, "Test step")
        step_store.update_step_passes(test_subtask["id"], 1, True)

        updated = step_store.update_step_passes(test_subtask["id"], 1, False)

        assert updated is not None
        assert updated["passes"] is False
        assert updated["passed_at"] is None

    def test_update_step_passes_toggle(self, test_subtask: dict[str, Any]) -> None:
        """Test toggling step pass status multiple times."""
        step_store.create_step(test_subtask["id"], 1, "Test step")

        # Toggle on
        updated1 = step_store.update_step_passes(test_subtask["id"], 1, True)
        assert updated1 is not None
        assert updated1["passes"] is True

        # Toggle off
        updated2 = step_store.update_step_passes(test_subtask["id"], 1, False)
        assert updated2 is not None
        assert updated2["passes"] is False

        # Toggle on again
        updated3 = step_store.update_step_passes(test_subtask["id"], 1, True)
        assert updated3 is not None
        assert updated3["passes"] is True

    def test_update_step_passes_nonexistent(self, test_subtask: dict[str, Any]) -> None:
        """Test updating non-existent step returns None."""
        result = step_store.update_step_passes(test_subtask["id"], 999, True)

        assert result is None


class TestBulkCreateSteps:
    """Tests for bulk_create_steps function."""

    def test_bulk_create_steps_basic(self, test_subtask: dict[str, Any]) -> None:
        """Test bulk creating multiple steps."""
        descriptions = ["Step 1", "Step 2", "Step 3"]

        created = step_store.bulk_create_steps(test_subtask["id"], descriptions)

        assert len(created) == 3
        assert created[0]["step_number"] == 1
        assert created[1]["step_number"] == 2
        assert created[2]["step_number"] == 3
        assert created[0]["description"] == "Step 1"

    def test_bulk_create_steps_empty(self, test_subtask: dict[str, Any]) -> None:
        """Test bulk creating with empty list."""
        created = step_store.bulk_create_steps(test_subtask["id"], [])

        assert created == []

    def test_bulk_create_steps_single(self, test_subtask: dict[str, Any]) -> None:
        """Test bulk creating single step."""
        created = step_store.bulk_create_steps(test_subtask["id"], ["Only step"])

        assert len(created) == 1
        assert created[0]["step_number"] == 1
        assert created[0]["description"] == "Only step"


class TestDeleteStepsForSubtask:
    """Tests for delete_steps_for_subtask function."""

    def test_delete_steps_basic(self, test_subtask: dict[str, Any]) -> None:
        """Test deleting all steps for a subtask."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3"])

        count = step_store.delete_steps_for_subtask(test_subtask["id"])

        assert count == 3

        # Verify deletion
        steps = step_store.get_steps_for_subtask(test_subtask["id"])
        assert steps == []

    def test_delete_steps_empty(self, test_subtask: dict[str, Any]) -> None:
        """Test deleting from subtask with no steps."""
        count = step_store.delete_steps_for_subtask(test_subtask["id"])

        assert count == 0

    def test_delete_steps_nonexistent_subtask(self) -> None:
        """Test deleting steps for non-existent subtask."""
        count = step_store.delete_steps_for_subtask("nonexistent-subtask")

        assert count == 0


class TestGetStepSummary:
    """Tests for get_step_summary function."""

    def test_step_summary_empty(self, test_subtask: dict[str, Any]) -> None:
        """Test summary with no steps."""
        summary = step_store.get_step_summary(test_subtask["id"])

        assert summary["total"] == 0
        assert summary["completed"] == 0
        assert summary["progress_percent"] == 0

    def test_step_summary_all_incomplete(self, test_subtask: dict[str, Any]) -> None:
        """Test summary with all steps incomplete."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3"])

        summary = step_store.get_step_summary(test_subtask["id"])

        assert summary["total"] == 3
        assert summary["completed"] == 0
        assert summary["progress_percent"] == 0

    def test_step_summary_partial(self, test_subtask: dict[str, Any]) -> None:
        """Test summary with partial completion."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3", "Step 4"])
        step_store.update_step_passes(test_subtask["id"], 1, True)
        step_store.update_step_passes(test_subtask["id"], 2, True)

        summary = step_store.get_step_summary(test_subtask["id"])

        assert summary["total"] == 4
        assert summary["completed"] == 2
        assert summary["progress_percent"] == 50.0

    def test_step_summary_all_complete(self, test_subtask: dict[str, Any]) -> None:
        """Test summary with all steps complete."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2"])
        step_store.update_step_passes(test_subtask["id"], 1, True)
        step_store.update_step_passes(test_subtask["id"], 2, True)

        summary = step_store.get_step_summary(test_subtask["id"])

        assert summary["total"] == 2
        assert summary["completed"] == 2
        assert summary["progress_percent"] == 100.0

    def test_step_summary_nonexistent_subtask(self) -> None:
        """Test summary for non-existent subtask."""
        summary = step_store.get_step_summary("nonexistent-subtask")

        assert summary["total"] == 0
        assert summary["completed"] == 0
        assert summary["progress_percent"] == 0


class TestStepGates:
    """Tests for step sequential completion gate.

    Steps are progress trackers. Out-of-order completion logs info.
    Force param has been removed - no bypass allowed.
    """

    def test_step_gate_allows_out_of_order_completion(self, test_subtask: dict[str, Any]) -> None:
        """Can mark step 2 as passed even if step 1 is not passed (logs info)."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3"])

        result = step_store.update_step_passes(test_subtask["id"], step_number=2, passes=True)
        assert result is not None
        assert result["passes"] is True

    def test_step_gate_allows_sequential_completion(self, test_subtask: dict[str, Any]) -> None:
        """Can mark step 2 as passed after step 1 is passed."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3"])

        # Mark step 1 as passed
        result1 = step_store.update_step_passes(test_subtask["id"], step_number=1, passes=True)
        assert result1 is not None
        assert result1["passes"] is True

        # Now step 2 should work
        result2 = step_store.update_step_passes(test_subtask["id"], step_number=2, passes=True)
        assert result2 is not None
        assert result2["passes"] is True

    def test_step_gate_force_param_removed(self, test_subtask: dict[str, Any]) -> None:
        """Force flag has been removed - no bypass available."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2"])

        # force=True should raise TypeError
        with pytest.raises(TypeError, match="unexpected keyword argument 'force'"):
            fn: Any = step_store.update_step_passes
            fn(test_subtask["id"], step_number=2, passes=True, force=True)

    def test_step_gate_first_step_no_check(self, test_subtask: dict[str, Any]) -> None:
        """First step has no gate check (no previous steps)."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2"])

        # Step 1 should always work
        result = step_store.update_step_passes(test_subtask["id"], step_number=1, passes=True)
        assert result is not None
        assert result["passes"] is True

    def test_step_gate_logs_missing_steps(self, test_subtask: dict[str, Any]) -> None:
        """Gate logs missing steps but allows completion."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3"])

        result = step_store.update_step_passes(test_subtask["id"], step_number=3, passes=True)
        assert result is not None
        assert result["passes"] is True

    def test_clearing_step_has_no_gate(self, test_subtask: dict[str, Any]) -> None:
        """Setting passes=False has no gate check (can clear any step)."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2"])

        # Can clear step 2 even if step 1 is not passed
        result = step_store.update_step_passes(test_subtask["id"], step_number=2, passes=False)
        assert result is not None
        assert result["passes"] is False


class TestInsertStep:
    """Tests for insert_step function."""

    def test_insert_step_at_beginning(self, test_subtask: dict[str, Any]) -> None:
        """Insert at position 1 shifts all existing steps."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2"])

        inserted = step_store.insert_step(test_subtask["id"], 1, "New First Step")

        assert inserted["step_number"] == 1
        assert inserted["description"] == "New First Step"

        steps = step_store.get_steps_for_subtask(test_subtask["id"])
        assert len(steps) == 3
        assert steps[0]["description"] == "New First Step"
        assert steps[1]["description"] == "Step 1"
        assert steps[1]["step_number"] == 2
        assert steps[2]["description"] == "Step 2"
        assert steps[2]["step_number"] == 3

    def test_insert_step_in_middle(self, test_subtask: dict[str, Any]) -> None:
        """Insert in middle shifts only steps at and after position."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3"])

        inserted = step_store.insert_step(test_subtask["id"], 2, "New Middle Step")

        assert inserted["step_number"] == 2

        steps = step_store.get_steps_for_subtask(test_subtask["id"])
        assert len(steps) == 4
        assert steps[0]["description"] == "Step 1"
        assert steps[0]["step_number"] == 1
        assert steps[1]["description"] == "New Middle Step"
        assert steps[1]["step_number"] == 2
        assert steps[2]["description"] == "Step 2"
        assert steps[2]["step_number"] == 3
        assert steps[3]["description"] == "Step 3"
        assert steps[3]["step_number"] == 4

    def test_insert_step_at_end(self, test_subtask: dict[str, Any]) -> None:
        """Insert at position after last step acts like append."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2"])

        inserted = step_store.insert_step(test_subtask["id"], 3, "Step 3")

        assert inserted["step_number"] == 3

        steps = step_store.get_steps_for_subtask(test_subtask["id"])
        assert len(steps) == 3
        assert steps[2]["description"] == "Step 3"

    def test_insert_step_empty_subtask(self, test_subtask: dict[str, Any]) -> None:
        """Insert into empty subtask works."""
        inserted = step_store.insert_step(test_subtask["id"], 1, "First Step")

        assert inserted["step_number"] == 1

        steps = step_store.get_steps_for_subtask(test_subtask["id"])
        assert len(steps) == 1

    def test_insert_step_invalid_position(self, test_subtask: dict[str, Any]) -> None:
        """Position < 1 raises ValueError."""
        with pytest.raises(ValueError, match="Position must be >= 1"):
            step_store.insert_step(test_subtask["id"], 0, "Invalid")


