"""Tests for issue-to-task closeout helpers."""

from __future__ import annotations

from unittest.mock import patch

from app.services.task_issue_mapper import QAIssue, close_task_for_issue


def _issue(task_id: str | None = "task-123") -> QAIssue:
    return QAIssue(
        id=17,
        project_id="summitflow",
        issue_type="complexity",
        severity="warning",
        title="Too complex",
        description=None,
        file_path="backend/app/foo.py",
        st_task_id=task_id,
    )


def test_close_task_for_issue_updates_status_without_shelling_out() -> None:
    with (
        patch(
            "app.services.task_issue_mapper.task_store.get_task",
            return_value={"id": "task-123", "status": "pending"},
        ),
        patch("app.services.task_issue_mapper.task_store.update_task_status") as mock_update,
        patch("app.services.task_issue_mapper.log_task_event") as mock_log,
    ):
        closed = close_task_for_issue(_issue())

    assert closed is True
    mock_update.assert_called_once_with("task-123", "cancelled")
    mock_log.assert_called_once()


def test_close_task_for_issue_skips_terminal_tasks() -> None:
    with (
        patch(
            "app.services.task_issue_mapper.task_store.get_task",
            return_value={"id": "task-123", "status": "completed"},
        ),
        patch("app.services.task_issue_mapper.task_store.update_task_status") as mock_update,
        patch("app.services.task_issue_mapper.log_task_event") as mock_log,
    ):
        closed = close_task_for_issue(_issue())

    assert closed is False
    mock_update.assert_not_called()
    mock_log.assert_not_called()
