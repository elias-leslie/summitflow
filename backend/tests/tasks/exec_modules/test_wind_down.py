"""Tests for wind_down terminal-status preservation."""

from __future__ import annotations

from unittest.mock import patch

from app.tasks.autonomous.exec_modules.session import wind_down


@patch("app.tasks.autonomous.exec_modules.session.emit_log")
@patch("app.tasks.autonomous.exec_modules.session.log_task_event")
@patch("app.tasks.autonomous.exec_modules.session.task_store")
def test_wind_down_preserves_completed_status(mock_store, _log, _emit) -> None:
    """When the orchestrator already declared completed, wind-down must not reset.

    Regression for F2: agent-declared success previously raised ExecutionInterrupted
    at the next checkpoint; wind_down then flipped status back to 'pending', erasing
    the terminal signal and leaving the orphan commit on the task branch.
    """
    mock_store.get_task.return_value = {"id": "t-1", "status": "completed"}
    state = wind_down("t-1", [], [], "task_status=completed")
    assert state.paused is True
    mock_store.update_task_status.assert_not_called()


@patch("app.tasks.autonomous.exec_modules.session.emit_log")
@patch("app.tasks.autonomous.exec_modules.session.log_task_event")
@patch("app.tasks.autonomous.exec_modules.session.task_store")
def test_wind_down_preserves_failed_and_cancelled(mock_store, _log, _emit) -> None:
    for terminal in ("failed", "cancelled"):
        mock_store.reset_mock()
        mock_store.get_task.return_value = {"id": "t-1", "status": terminal}
        wind_down("t-1", [], [], "any_reason")
        mock_store.update_task_status.assert_not_called()


@patch("app.tasks.autonomous.exec_modules.session.emit_log")
@patch("app.tasks.autonomous.exec_modules.session.log_task_event")
@patch("app.tasks.autonomous.exec_modules.session.task_store")
def test_wind_down_resets_running_to_pending(mock_store, _log, _emit) -> None:
    """Mid-flight runs still flip back to pending so the queue can re-pick them."""
    mock_store.get_task.return_value = {"id": "t-1", "status": "running"}
    wind_down("t-1", [], [], "max_iterations")
    mock_store.update_task_status.assert_called_once_with("t-1", "pending")
