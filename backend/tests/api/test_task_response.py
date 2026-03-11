"""Tests for task_to_response ensuring all fields propagate correctly."""

from __future__ import annotations

from unittest.mock import patch

from app.api.tasks.response import task_to_response


def _minimal_task(**overrides: object) -> dict[str, object]:
    """Build a minimal task dict with required fields."""
    base: dict[str, object] = {
        "id": "task-test-1",
        "project_id": "test-project",
        "capability_id": None,
        "title": "Test task",
        "description": "A test task",
        "status": "pending",
        "error_message": None,
        "branch_name": None,
        "commits": [],
        "total_sessions": 0,
        "total_tokens_used": 0,
        "created_at": None,
        "started_at": None,
        "completed_at": None,
        "priority": 2,
        "labels": [],
        "task_type": "task",
        "parent_task_id": None,
        "autonomous": False,
        "ai_review": True,
    }
    base.update(overrides)
    return base


class TestTaskToResponse:
    """Tests for task_to_response field mapping."""

    @patch("app.api.tasks.response.get_step_count_for_task", return_value=0)
    def test_ai_review_true_propagated(self, _mock: object) -> None:
        """ai_review=True in task dict appears in response."""
        task = _minimal_task(ai_review=True)
        response = task_to_response(task)
        assert response.ai_review

    @patch("app.api.tasks.response.get_step_count_for_task", return_value=0)
    def test_ai_review_false_propagated(self, _mock: object) -> None:
        """ai_review=False in task dict appears in response (the critical case)."""
        task = _minimal_task(ai_review=False)
        response = task_to_response(task)
        assert not response.ai_review

    @patch("app.api.tasks.response.get_step_count_for_task", return_value=0)
    def test_ai_review_missing_defaults_true(self, _mock: object) -> None:
        """Missing ai_review key defaults to True (backward compat)."""
        task = _minimal_task()
        del task["ai_review"]
        response = task_to_response(task)
        assert response.ai_review

    @patch("app.api.tasks.response.get_step_count_for_task", return_value=0)
    def test_autonomous_propagated(self, _mock: object) -> None:
        """autonomous field also propagates (sanity check for similar fields)."""
        task = _minimal_task(autonomous=True)
        response = task_to_response(task)
        assert response.autonomous

    @patch("app.api.tasks.response.get_step_count_for_task", return_value=0)
    def test_execution_mode_propagated(self, _mock: object) -> None:
        """execution_mode is the source-of-truth task execution control."""
        task = _minimal_task(execution_mode="manual")
        response = task_to_response(task)
        assert response.execution_mode == "manual"
        assert not response.autonomous

    @patch("app.api.tasks.response.get_step_count_for_task", return_value=0)
    def test_execution_mode_autonomous_sets_compat_flag(self, _mock: object) -> None:
        task = _minimal_task(execution_mode="autonomous", autonomous=False)
        response = task_to_response(task)
        assert response.execution_mode == "autonomous"
        assert response.autonomous
