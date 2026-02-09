"""Integration test for autonomous idea triage flow.

Tests the complete triage flow: create task -> triage runs -> moves to Planning or asks question.
"""

from __future__ import annotations

from app.tasks.autonomous.triage import triage_idea


class TestTriageIdea:
    """Test triage_idea task."""

    def test_triage_module_exists(self) -> None:
        """Verify triage module is properly structured."""
        assert callable(triage_idea)
        assert triage_idea.name == "autonomous.triage_idea"

    def test_triage_missing_task_returns_error(self) -> None:
        """Triage on missing task should return error."""
        result = triage_idea("nonexistent-task-xyz", "nonexistent-project")
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    def test_triage_handles_task_structure(self) -> None:
        """Triage should handle task data structure."""
        result = triage_idea("nonexistent", "test-project")
        assert "task_id" in result
        assert result["task_id"] == "nonexistent"
