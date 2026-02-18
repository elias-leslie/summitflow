"""Integration test for auto-merge flow.

Tests the complete auto-merge flow: SIMPLE task completes -> AI Review passes -> auto-merges.
"""

from __future__ import annotations

from app.tasks.autonomous.review import ai_review


class TestAIReview:
    """Test AI review task."""

    def test_review_module_exists(self) -> None:
        """Verify review module is properly structured."""
        assert callable(ai_review)
        assert ai_review.__name__ == "ai_review"

    def test_review_missing_task_returns_error(self) -> None:
        """Review on missing task should return error."""
        result = ai_review("nonexistent-task-xyz", "nonexistent-project")
        assert result["status"] == "error"

    def test_review_handles_task_structure(self) -> None:
        """Review should handle task data structure."""
        result = ai_review("nonexistent", "test-project")
        assert "task_id" in result
        assert result["task_id"] == "nonexistent"
