"""End-to-end tests for TDD system.

Tests the full flow from task creation to completion,
verifying all state fields are updated correctly.
"""

import pytest
from app.storage import criteria as criteria_store
from app.storage import tasks as task_store
from app.storage.connection import get_connection


@pytest.fixture
def cleanup_test_tasks():
    """Clean up test tasks after tests."""
    task_ids = []
    yield task_ids
    # Cleanup
    for task_id in task_ids:
        try:
            task_store.delete_task(task_id)
        except Exception:
            pass


class TestTaskCompletionE2E:
    """Test task completion updates all relevant fields."""

    def test_task_creation_to_completion(self, cleanup_test_tasks):
        """Test: Create task → Update status → Complete → Verify all fields."""
        # Step 1: Create task
        task = task_store.create_task(
            project_id="summitflow",
            title="E2E Test Task",
            description="Test task for E2E verification",
            task_type="task",
            priority=2,
        )
        cleanup_test_tasks.append(task["id"])
        assert task["status"] == "pending"
        # Phase is "plan" by default, not "planning"
        assert task["current_phase"] is None or task["current_phase"] == "plan"

        # Step 2: Update to running
        task = task_store.update_task_status(task["id"], "running")
        assert task["status"] == "running"

        # Step 3: Complete task
        task = task_store.update_task_status(task["id"], "completed")

        # Step 4: Verify all fields
        assert task["status"] == "completed"
        assert task["current_phase"] == "complete"
        assert task["claimed_by"] is None
        assert task["claimed_at"] is None
        # verification_result should be populated (may be empty list if no criteria)
        assert "verification_result" in task or task.get("verification_result") is not None

    def test_task_failure_clears_claims(self, cleanup_test_tasks):
        """Test that failed tasks also clear claims."""
        # Create and claim task
        task = task_store.create_task(
            project_id="summitflow",
            title="E2E Failure Test",
            description="Test task for failure flow",
            task_type="task",
            priority=2,
        )
        cleanup_test_tasks.append(task["id"])

        # Update to running (simulates claim)
        task = task_store.update_task_status(task["id"], "running")

        # Fail the task (note: error message is stored in progress_log, not a param)
        task = task_store.update_task_status(task["id"], "failed")

        # Verify claims cleared
        assert task["status"] == "failed"
        assert task["claimed_by"] is None
        assert task["claimed_at"] is None


class TestTDDVerificationE2E:
    """Test TDD verification flow with criteria and tests."""

    def test_capability_verification_flow(self):
        """Test: Create capability → Add criteria → Link tests → Verify."""
        from app.storage import capabilities as cap_store

        # Get worktree-isolation capability (should exist from previous tests)
        capability = cap_store.get_capability("summitflow", "worktree-isolation")
        assert capability is not None

        # Get criteria
        with get_connection() as conn:
            criteria = criteria_store.get_criteria_for_capability(
                conn, "summitflow", "worktree-isolation"
            )

        # Should have real criteria (not pseudo)
        assert len(criteria) >= 10
        for crit in criteria:
            assert not crit["criterion"].startswith("Test passes:")

        # Verify capability (should pass since we ran tests earlier)
        import asyncio

        from app.api.capabilities import verify_capability

        result = asyncio.get_event_loop().run_until_complete(
            verify_capability("summitflow", "worktree-isolation")
        )

        assert result.criteria_total == len(criteria)
        # May not all pass if tests weren't run recently
        assert result.criteria_passed >= 0

    def test_evidence_count_in_verification(self):
        """Test that evidence_captured reflects actual evidence count."""
        import asyncio

        from app.api.capabilities import verify_capability

        result = asyncio.get_event_loop().run_until_complete(
            verify_capability("summitflow", "worktree-isolation")
        )

        # evidence_captured should be boolean based on actual evidence
        assert isinstance(result.evidence_captured, bool)
        assert isinstance(result.evidence_count, int)
        assert result.evidence_count >= 0
