"""Tests for assert_task_runnable interrupt-status semantics."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.tasks.autonomous.exec_modules.interruption import (
    ExecutionInterrupted,
    assert_task_runnable,
)


@patch("app.tasks.autonomous.exec_modules.interruption.task_store")
def test_completed_status_does_not_interrupt(mock_store) -> None:
    """Agent-declared success (status=completed) must fall through, not raise.

    Regression for F2 'stuck-after-success': the agent's final `st done` call
    flipped status to 'completed'; the next checkpoint raised ExecutionInterrupted,
    wind_down reset to 'pending', and handle_completion short-circuited — leaving
    the orphan commit on the task branch.
    """
    mock_store.get_task.return_value = {"id": "t-1", "status": "completed"}
    assert_task_runnable("t-1", "proj-1", "self_heal_attempt_0")


@patch("app.tasks.autonomous.exec_modules.interruption.emit_log")
@patch("app.tasks.autonomous.exec_modules.interruption.task_store")
@pytest.mark.parametrize("status", ["paused", "cancelled", "failed"])
def test_user_initiated_stops_still_interrupt(mock_store, _mock_emit, status) -> None:
    mock_store.get_task.return_value = {"id": "t-1", "status": status}
    with pytest.raises(ExecutionInterrupted) as exc_info:
        assert_task_runnable("t-1", "proj-1", "between_subtasks")
    assert exc_info.value.status == status
