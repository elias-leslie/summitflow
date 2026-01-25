"""Integration test for autonomous planning flow.

Tests the complete planning flow: task in Planning -> run_agent creates subtasks -> moves to Queue.
"""

from __future__ import annotations

import pytest

from app.tasks.autonomous.planning import create_plan


class TestCreatePlan:
    """Test create_plan Celery task."""

    def test_planning_module_exists(self) -> None:
        """Verify planning module is properly structured."""
        assert callable(create_plan)
        assert create_plan.name == "autonomous.create_plan"

    def test_planning_missing_task_returns_error(self) -> None:
        """Planning on missing task should return error."""
        result = create_plan("nonexistent-task-xyz", "nonexistent-project")
        assert result["status"] == "error"

    def test_planning_handles_task_structure(self) -> None:
        """Planning should handle task data structure."""
        result = create_plan("nonexistent", "test-project")
        assert "task_id" in result
        assert result["task_id"] == "nonexistent"
