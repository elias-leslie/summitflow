"""Tests for completion-handler runtime evaluator integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.intent_check import IntentCheckResult


@patch("app.tasks.autonomous.exec_modules.completion_handler.wake_persona")
@patch("app.tasks.autonomous.exec_modules.completion_handler.transition_to_review_or_complete")
@patch("app.tasks.autonomous.exec_modules.completion_handler.build_successful_completion_verification")
@patch("app.tasks.autonomous.exec_modules.completion_handler.run_runtime_evaluator")
@patch("app.tasks.autonomous.exec_modules.completion_handler._run_intent_check")
@patch("app.tasks.autonomous.exec_modules.completion_handler.run_quality_gate_with_autofix")
@patch("app.tasks.autonomous.exec_modules.completion_handler.check_diff_gate")
def test_handle_successful_completion_runs_runtime_evaluator_when_required(
    mock_diff_gate: MagicMock,
    mock_quality_gate: MagicMock,
    mock_intent: MagicMock,
    mock_runtime_eval: MagicMock,
    mock_verification: MagicMock,
    mock_transition: MagicMock,
    _mock_wake: MagicMock,
) -> None:
    from app.tasks.autonomous.exec_modules.completion_handler import handle_successful_completion
    from app.tasks.autonomous.exec_modules.runtime_evaluator import RuntimeEvaluationResult

    mock_diff_gate.return_value = MagicMock(passed=True, summary="ok")
    mock_quality_gate.return_value = True
    mock_intent.return_value = IntentCheckResult(
        passed=True,
        objective_met=True,
        spirit_violated=False,
        confidence=95,
        summary="intent pass",
    )
    mock_runtime_eval.return_value = RuntimeEvaluationResult(
        mode="runtime_eval",
        passed=True,
        summary="runtime pass",
        criteria=[],
        screenshots=[],
        api_results=[],
        design_result=None,
    )
    mock_verification.return_value = {"execution_clean": True}

    result = handle_successful_completion("task-1", "summitflow", "/tmp/project", results=[])

    assert result is True
    mock_runtime_eval.assert_called_once_with("task-1", "summitflow")
    mock_transition.assert_called_once()


@patch("app.tasks.autonomous.exec_modules.completion_handler.wake_persona")
@patch("app.tasks.autonomous.exec_modules.completion_handler.notify_failure")
@patch("app.tasks.autonomous.exec_modules.completion_handler.emit_error")
@patch("app.tasks.autonomous.exec_modules.completion_handler.task_store")
@patch("app.tasks.autonomous.exec_modules.completion_handler.run_runtime_evaluator")
@patch("app.tasks.autonomous.exec_modules.completion_handler._run_intent_check")
@patch("app.tasks.autonomous.exec_modules.completion_handler.run_quality_gate_with_autofix")
@patch("app.tasks.autonomous.exec_modules.completion_handler.check_diff_gate")
def test_handle_successful_completion_blocks_when_runtime_evaluator_fails(
    mock_diff_gate: MagicMock,
    mock_quality_gate: MagicMock,
    mock_intent: MagicMock,
    mock_runtime_eval: MagicMock,
    mock_task_store: MagicMock,
    mock_emit_error: MagicMock,
    mock_notify_failure: MagicMock,
    mock_wake: MagicMock,
) -> None:
    from app.tasks.autonomous.exec_modules.completion_handler import handle_successful_completion
    from app.tasks.autonomous.exec_modules.runtime_evaluator import RuntimeEvaluationResult

    mock_diff_gate.return_value = MagicMock(passed=True, summary="ok")
    mock_quality_gate.return_value = True
    mock_intent.return_value = IntentCheckResult(
        passed=True,
        objective_met=True,
        spirit_violated=False,
        confidence=95,
        summary="intent pass",
    )
    mock_runtime_eval.return_value = RuntimeEvaluationResult(
        mode="runtime_eval_plus_design",
        passed=False,
        summary="dashboard screenshot missing expected widget",
        criteria=[],
        screenshots=[],
        api_results=[],
        design_result=None,
    )

    result = handle_successful_completion("task-1", "summitflow", "/tmp/project", results=[])

    assert result is False
    mock_task_store.update_task_status.assert_called_once_with("task-1", "failed")
    mock_emit_error.assert_called_once()
    mock_notify_failure.assert_called_once()
    mock_wake.assert_called_once()
