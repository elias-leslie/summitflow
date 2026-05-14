"""Tests for lean task completion handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


@patch("app.tasks.autonomous.exec_modules.completion_handler.transition_to_complete")
@patch("app.tasks.autonomous.exec_modules.completion_handler.build_successful_completion_verification")
@patch("app.tasks.autonomous.exec_modules.completion_handler.run_quality_gate")
@patch("app.tasks.autonomous.exec_modules.completion_handler.check_diff_gate")
def test_handle_successful_completion_completes_after_diff_and_quality_gates(
    mock_diff_gate: MagicMock,
    mock_quality_gate: MagicMock,
    mock_verification: MagicMock,
    mock_transition: MagicMock,
) -> None:
    from app.tasks.autonomous.exec_modules.completion_handler import handle_successful_completion

    mock_diff_gate.return_value = MagicMock(passed=True, summary="ok")
    mock_quality_gate.return_value = True
    mock_verification.return_value = {"execution_clean": True}

    result = handle_successful_completion("task-1", "summitflow", "/tmp/project", results=[])

    assert result is True
    mock_transition.assert_called_once_with(
        "task-1",
        "summitflow",
        "All subtasks passed + quality gate passed (clean=True)",
        None,
    )


@patch("app.tasks.autonomous.exec_modules.completion_handler.notify_failure")
@patch("app.tasks.autonomous.exec_modules.completion_handler.emit_error")
@patch("app.tasks.autonomous.exec_modules.completion_handler.emit_task_transition")
@patch("app.tasks.autonomous.exec_modules.completion_handler.task_store")
@patch("app.tasks.autonomous.exec_modules.completion_handler.run_quality_gate")
@patch("app.tasks.autonomous.exec_modules.completion_handler.check_diff_gate")
def test_handle_successful_completion_blocks_when_diff_gate_fails(
    mock_diff_gate: MagicMock,
    mock_quality_gate: MagicMock,
    mock_task_store: MagicMock,
    mock_transition: MagicMock,
    mock_emit_error: MagicMock,
    mock_notify_failure: MagicMock,
) -> None:
    from app.tasks.autonomous.exec_modules.completion_handler import handle_successful_completion

    mock_diff_gate.return_value = MagicMock(passed=False, summary="no changes")

    result = handle_successful_completion("task-1", "summitflow", "/tmp/project", results=[])

    assert result is False
    mock_quality_gate.assert_not_called()
    mock_task_store.update_task_status.assert_called_once_with("task-1", "failed")
    mock_transition.assert_called_once()
    mock_emit_error.assert_called_once()
    mock_notify_failure.assert_called_once()


@patch("app.tasks.autonomous.exec_modules.completion_handler.notify_failure")
@patch("app.tasks.autonomous.exec_modules.completion_handler.emit_error")
@patch("app.tasks.autonomous.exec_modules.completion_handler.emit_task_transition")
@patch("app.tasks.autonomous.exec_modules.completion_handler.task_store")
@patch("app.tasks.autonomous.exec_modules.completion_handler.run_quality_gate")
@patch("app.tasks.autonomous.exec_modules.completion_handler.check_diff_gate")
def test_handle_successful_completion_blocks_when_quality_gate_fails(
    mock_diff_gate: MagicMock,
    mock_quality_gate: MagicMock,
    mock_task_store: MagicMock,
    mock_transition: MagicMock,
    mock_emit_error: MagicMock,
    mock_notify_failure: MagicMock,
) -> None:
    from app.tasks.autonomous.exec_modules.completion_handler import handle_successful_completion

    mock_diff_gate.return_value = MagicMock(passed=True, summary="ok")
    mock_quality_gate.return_value = False

    result = handle_successful_completion("task-1", "summitflow", "/tmp/project", results=[])

    assert result is False
    mock_task_store.update_task_status.assert_called_once_with("task-1", "failed")
    mock_transition.assert_called_once_with("task-1", "failed", "Quality gate failed")
    mock_emit_error.assert_called_once()
    mock_notify_failure.assert_called_once()
