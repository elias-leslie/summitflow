"""Tests for sequential subtask execution."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.task_lane_preflight import TaskLaneConflictCheck
from app.storage.subtasks import create_subtask, get_subtasks_for_task
from app.storage.tasks import create_task
from app.storage.tasks import delete_task as _delete_task
from app.tasks.autonomous.exec_modules.execution_loop import execute_subtask_loop
from app.tasks.autonomous.exec_modules.interruption import ExecutionInterrupted
from app.tasks.autonomous.exec_modules.orchestrator import start_execution
from app.tasks.autonomous.exec_modules.session import WindDownState


def delete_task(task_id: str) -> None:
    """Test helper that tolerates repeated cleanup for the same task."""
    try:
        _delete_task(task_id)
    except Exception as exc:  # pragma: no cover - defensive cleanup path
        if "does not exist" not in str(exc):
            raise


@pytest.fixture
def cleanup_task() -> Any:
    """Provide task cleanup helper to integration tests."""

    def _cleanup(task_id: str) -> None:
        delete_task(task_id)

    return _cleanup


def test_subtask_execution_stops_at_max_iterations() -> None:
    """Test that execution loop stops when MAX_ITERATIONS is reached."""
    task_id = "test-task"
    project_id = "test-project"
    project_path = "/tmp/test-project"

    subtasks = [{"subtask_id": f"{i}.1", "description": f"Task {i}"} for i in range(1, 10)]

    result_sequence = [
        {"status": "passed", "subtask_id": "1.1"},
        {"status": "passed", "subtask_id": "2.1"},
        {"status": "passed", "subtask_id": "3.1"},
    ]

    with patch("app.tasks.autonomous.exec_modules.execution_loop.MAX_ITERATIONS", 3), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.execute_subtask",
        side_effect=result_sequence,
    ) as mock_execute, patch(
        "app.tasks.autonomous.exec_modules.execution_loop.emit_log"
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.emit_progress"
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.has_uncommitted_changes",
        return_value=False,
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop._check_health_or_wait",
        return_value=True,
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.wind_down",
        return_value=WindDownState(paused=True, reason="max_iterations"),
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.assert_task_runnable",
    ) as mock_assert_runnable, patch(
        "app.tasks.autonomous.exec_modules.execution_loop.wind_down",
        return_value=WindDownState(paused=True, reason="max_iterations"),
    ) as mock_wind_down:
        results, completed_count, wind_down_state = execute_subtask_loop(
            task_id=task_id,
            project_id=project_id,
            project_path=project_path,
            incomplete_subtasks=subtasks,
            total_subtasks=len(subtasks),
            completed_count=0,
            task_type=None,
            agent_override=None,
        )

    assert len(results) == 3
    assert completed_count == 3
    assert wind_down_state == WindDownState(paused=True, reason="max_iterations")
    assert mock_execute.call_count == 3
    mock_assert_runnable.assert_called()
    mock_wind_down.assert_called_once()


def test_subtask_execution_continues_after_failures() -> None:
    """Test that execution loop continues after subtask failures."""
    task_id = "test-task"
    project_id = "test-project"
    project_path = "/tmp/test-project"

    subtasks = [
        {"subtask_id": "1.1", "description": "First"},
        {"subtask_id": "1.2", "description": "Second"},
        {"subtask_id": "2.1", "description": "Third"},
    ]

    results_sequence = [
        {"status": "passed", "subtask_id": "1.1"},
        {"status": "failed", "subtask_id": "1.2", "issue_id": "test_error_1", "step_results": []},
        {"status": "passed", "subtask_id": "2.1"},
    ]

    with patch(
        "app.tasks.autonomous.exec_modules.execution_loop.execute_subtask",
        side_effect=results_sequence,
    ) as mock_execute, patch(
        "app.tasks.autonomous.exec_modules.execution_loop.emit_log"
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.emit_progress"
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.has_uncommitted_changes",
        return_value=False,
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop._check_health_or_wait",
        return_value=True,
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.assert_task_runnable",
    ):
        results, completed_count, wind_down_state = execute_subtask_loop(
            task_id=task_id,
            project_id=project_id,
            project_path=project_path,
            incomplete_subtasks=subtasks,
            total_subtasks=len(subtasks),
            completed_count=0,
            task_type=None,
            agent_override=None,
        )

    assert len(results) == 3
    assert completed_count == 3
    assert wind_down_state is None
    assert mock_execute.call_count == 3
    assert results[0]["status"] == "passed"
    assert results[1]["status"] == "failed"
    assert results[2]["status"] == "passed"


def test_subtask_execution_triggers_circuit_breaker_after_repeated_failures() -> None:
    """Test that circuit breaker triggers after repeated same issue failures."""
    task_id = "test-task"
    project_id = "test-project"
    project_path = "/tmp/test-project"

    subtasks = [
        {"subtask_id": "1.1", "description": "First"},
        {"subtask_id": "1.2", "description": "Second"},
        {"subtask_id": "1.3", "description": "Third"},
        {"subtask_id": "2.1", "description": "Fourth"},
    ]

    results_sequence = [
        {"status": "failed", "subtask_id": "1.1", "issue_id": "same_error", "step_results": []},
        {"status": "failed", "subtask_id": "1.2", "issue_id": "same_error", "step_results": []},
        {"status": "failed", "subtask_id": "1.3", "issue_id": "same_error", "step_results": []},
        {"status": "failed", "subtask_id": "2.1", "issue_id": "same_error", "step_results": []},
    ]

    with patch(
        "app.tasks.autonomous.exec_modules.execution_loop.execute_subtask",
        side_effect=results_sequence,
    ) as mock_execute, patch(
        "app.tasks.autonomous.exec_modules.execution_loop.supervisor_circuit_breaker_triage",
        return_value=False,
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.emit_log"
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.emit_progress"
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.task_store"
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.has_uncommitted_changes",
        return_value=False,
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop._check_health_or_wait",
        return_value=True,
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.assert_task_runnable",
    ):
        results, completed_count, wind_down_state = execute_subtask_loop(
            task_id=task_id,
            project_id=project_id,
            project_path=project_path,
            incomplete_subtasks=subtasks,
            total_subtasks=len(subtasks),
            completed_count=0,
            task_type=None,
            agent_override=None,
        )

    assert len(results) == 4
    assert completed_count == 4
    assert wind_down_state is None
    assert mock_execute.call_count == 4
    assert mock_execute.call_count == 4


def test_subtask_execution_winds_down_when_task_is_paused() -> None:
    """Execution loop should stop cleanly when the task is externally paused."""
    task_id = "test-paused-task"
    project_id = "test-project"
    project_path = "/tmp/test-project"

    subtasks = [
        {"subtask_id": "1.1", "description": "First"},
        {"subtask_id": "1.2", "description": "Second"},
    ]

    with patch(
        "app.tasks.autonomous.exec_modules.execution_loop.assert_task_runnable",
        side_effect=ExecutionInterrupted("paused", "task_status=paused"),
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.wind_down",
        return_value=WindDownState(paused=True, reason="task_status=paused"),
    ) as mock_wind_down, patch(
        "app.tasks.autonomous.exec_modules.execution_loop.emit_log"
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.has_uncommitted_changes",
        return_value=False,
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop._check_health_or_wait",
        return_value=True,
    ):
        results, completed_count, wind_down_state = execute_subtask_loop(
            task_id=task_id,
            project_id=project_id,
            project_path=project_path,
            incomplete_subtasks=subtasks,
            total_subtasks=len(subtasks),
            completed_count=0,
            task_type=None,
            agent_override=None,
        )

    assert results == []
    assert completed_count == 0
    assert wind_down_state == WindDownState(paused=True, reason="task_status=paused")
    mock_wind_down.assert_called_once_with(
        task_id,
        [],
        subtasks,
        "task_status=paused",
    )


def test_subtask_execution_orders_incomplete_work_by_dependencies() -> None:
    """Dependency order should win over incoming list order for incomplete subtasks."""
    task_id = "test-dependency-order"
    project_id = "test-project"
    project_path = "/tmp/test-project"

    subtasks = [
        {"subtask_id": "1.3", "description": "Third", "depends_on": ["1.2"]},
        {"subtask_id": "1.2", "description": "Second", "depends_on": ["1.1"]},
        {"subtask_id": "1.1", "description": "First"},
    ]
    result_sequence = [
        {"status": "passed", "subtask_id": "1.1"},
        {"status": "passed", "subtask_id": "1.2"},
        {"status": "passed", "subtask_id": "1.3"},
    ]

    with patch(
        "app.tasks.autonomous.exec_modules.execution_loop.execute_subtask",
        side_effect=result_sequence,
    ) as mock_execute, patch(
        "app.tasks.autonomous.exec_modules.execution_loop.emit_log"
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.emit_progress"
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.has_uncommitted_changes",
        return_value=False,
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop._check_health_or_wait",
        return_value=True,
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.assert_task_runnable",
    ):
        results, completed_count, wind_down_state = execute_subtask_loop(
            task_id=task_id,
            project_id=project_id,
            project_path=project_path,
            incomplete_subtasks=subtasks,
            total_subtasks=len(subtasks),
            completed_count=0,
            task_type=None,
            agent_override=None,
        )

    assert [call.args[1]["subtask_id"] for call in mock_execute.call_args_list] == ["1.1", "1.2", "1.3"]
    assert [result["subtask_id"] for result in results] == ["1.1", "1.2", "1.3"]
    assert completed_count == 3
    assert wind_down_state is None


@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts", return_value=TaskLaneConflictCheck())
@patch("app.tasks.autonomous.exec_modules.orchestrator.task_store")
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_subtasks_for_task")
@patch("app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator.setup_task_checkout", return_value="/tmp/checkout")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_subtask_loop")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_progress")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_agent_feedback")
def test_start_execution_orchestration_flow(
    _mock_feedback: MagicMock,
    mock_emit_progress: MagicMock,
    mock_emit_log: MagicMock,
    mock_loop: MagicMock,
    mock_setup: MagicMock,
    mock_validate: MagicMock,
    mock_get_subtasks: MagicMock,
    mock_task_store: MagicMock,
    _mock_lane_conflicts: MagicMock,
) -> None:
    """Verify that start_execution correctly orchestrates subtask execution."""
    task_id = "task-123"
    project_id = "proj-123"

    mock_task_store.get_task.return_value = {"id": task_id, "task_type": "task"}

    subtasks = [
        {"id": "s1", "subtask_id": "1.1", "passes": False},
        {"id": "s2", "subtask_id": "1.2", "passes": False},
        {"id": "s3", "subtask_id": "2.1", "passes": True},
    ]
    mock_get_subtasks.return_value = subtasks

    mock_loop.return_value = (
        [{"subtask_id": "1.1", "status": "passed"}, {"subtask_id": "1.2", "status": "passed"}],
        2,
        None,
    )

    with patch("app.tasks.autonomous.exec_modules.orchestrator.handle_successful_completion"):
        result = start_execution(task_id, project_id)

    assert result["status"] == "executed"
    mock_loop.assert_called_once()

    args = mock_loop.call_args[0]
    passed_incomplete_subtasks = args[3]
    assert len(passed_incomplete_subtasks) == 2
    assert passed_incomplete_subtasks[0]["subtask_id"] == "1.1"
    assert passed_incomplete_subtasks[1]["subtask_id"] == "1.2"

    mock_task_store.update_task_status.assert_called_with(task_id, "running")


@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts", return_value=TaskLaneConflictCheck())
@patch("app.tasks.autonomous.exec_modules.orchestrator.task_store")
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_subtasks_for_task")
@patch("app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator.setup_task_checkout", return_value="/tmp/checkout")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_subtask_loop")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_agent_feedback")
@patch("app.tasks.autonomous.exec_modules.orchestrator.handle_successful_completion", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_progress")
def test_start_execution_routes_completion_before_optional_feedback(
    mock_emit_progress: MagicMock,
    mock_emit_log: MagicMock,
    mock_handle_successful_completion: MagicMock,
    mock_feedback: MagicMock,
    mock_loop: MagicMock,
    mock_setup: MagicMock,
    mock_validate: MagicMock,
    mock_get_subtasks: MagicMock,
    mock_task_store: MagicMock,
    _mock_lane_conflicts: MagicMock,
) -> None:
    task_id = "task-123"
    project_id = "proj-123"

    mock_task_store.get_task.return_value = {"id": task_id, "task_type": "task"}
    mock_get_subtasks.return_value = [{"id": "s1", "subtask_id": "1.1", "passes": False}]
    mock_loop.return_value = ([{"subtask_id": "1.1", "status": "passed"}], 1, None)
    mock_feedback.side_effect = RuntimeError("feedback hang substitute")

    result = start_execution(task_id, project_id)

    assert result["status"] == "executed"
    mock_handle_successful_completion.assert_called_once()
    mock_feedback.assert_called_once()
    assert any("feedback collection failed after completion routing" in call.args[2] for call in mock_emit_log.call_args_list)


@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts", return_value=TaskLaneConflictCheck())
@patch("app.tasks.autonomous.exec_modules.orchestrator.task_store")
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_subtasks_for_task")
@patch("app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator.setup_task_checkout", return_value="/tmp/checkout")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_subtask_loop")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_agent_feedback")
@patch("app.tasks.autonomous.exec_modules.orchestrator.handle_failed_execution")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_progress")
def test_start_execution_collects_feedback_after_failed_run(
    mock_emit_progress: MagicMock,
    mock_emit_log: MagicMock,
    mock_handle_failed_execution: MagicMock,
    mock_feedback: MagicMock,
    mock_loop: MagicMock,
    mock_setup: MagicMock,
    mock_validate: MagicMock,
    mock_get_subtasks: MagicMock,
    mock_task_store: MagicMock,
    _mock_lane_conflicts: MagicMock,
) -> None:
    task_id = "task-failed"
    project_id = "proj-123"

    mock_task_store.get_task.return_value = {"id": task_id, "task_type": "task"}
    mock_get_subtasks.return_value = [{"id": "s1", "subtask_id": "1.1", "passes": False}]
    mock_loop.return_value = ([{"subtask_id": "1.1", "status": "failed"}], 0, None)

    result = start_execution(task_id, project_id)

    assert result["status"] == "executed"
    mock_handle_failed_execution.assert_called_once()
    mock_feedback.assert_called_once()


@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts", return_value=TaskLaneConflictCheck())
@patch("app.tasks.autonomous.exec_modules.orchestrator.task_store")
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_subtasks_for_task")
@patch("app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator.setup_task_checkout", return_value="/tmp/checkout")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_subtask_loop")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_progress")
def test_start_execution_reopens_passed_subtasks_for_conflict_resolution(
    mock_emit_progress: MagicMock,
    mock_emit_log: MagicMock,
    mock_loop: MagicMock,
    mock_setup: MagicMock,
    mock_validate: MagicMock,
    mock_get_subtasks: MagicMock,
    mock_task_store: MagicMock,
    _mock_lane_conflicts: MagicMock,
) -> None:
    task_id = "task-conflict"
    project_id = "proj-123"

    mock_task_store.get_task.return_value = {
        "id": task_id,
        "task_type": "task",
        "status": "conflicted",
        "conflict_info": {"conflicting_files": ["backend/app/services/tools/tool_handler.py"]},
    }
    mock_get_subtasks.return_value = [
        {"id": "s1", "subtask_id": "1.1", "passes": True},
    ]
    mock_loop.return_value = ([], 0, None)

    with patch("app.tasks.autonomous.exec_modules.orchestrator.handle_early_completion") as mock_early:
        start_execution(task_id, project_id)

    mock_loop.assert_not_called()
    mock_early.assert_called_once()


@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts", return_value=TaskLaneConflictCheck())
@patch("app.tasks.autonomous.exec_modules.orchestrator.task_store")
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_subtasks_for_task")
@patch("app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator._has_active_task_checkpoint", return_value=False)
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_task_checkout", return_value=object())
@patch("app.tasks.autonomous.exec_modules.orchestrator.setup_task_checkout")
@patch("app.tasks.autonomous.exec_modules.orchestrator.handle_early_completion", return_value={"status": "completed"})
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_progress")
def test_execute_task_locked_ignores_preserved_branch_without_active_checkpoint(
    mock_emit_progress: MagicMock,
    mock_emit_log: MagicMock,
    mock_early: MagicMock,
    mock_setup: MagicMock,
    mock_get_task_checkout: MagicMock,
    mock_has_checkpoint: MagicMock,
    mock_validate: MagicMock,
    mock_get_subtasks: MagicMock,
    mock_task_store: MagicMock,
    _mock_lane_conflicts: MagicMock,
) -> None:
    task_id = "task-complete"
    project_id = "summitflow"

    mock_task_store.get_task.return_value = {
        "id": task_id,
        "task_type": "refactor",
        "status": "completed",
    }
    mock_get_subtasks.return_value = [{"id": "s1", "subtask_id": "1.1", "passes": True}]

    result = start_execution(task_id, project_id)

    assert result == {"status": "completed"}
    mock_validate.assert_called_once_with(task_id, project_id)
    mock_has_checkpoint.assert_called_once_with(task_id, project_id)
    mock_get_task_checkout.assert_not_called()
    mock_setup.assert_not_called()
    mock_early.assert_called_once_with(task_id, project_id, 1, None)
    mock_emit_progress.assert_called_once_with(
        task_id,
        total_subtasks=1,
        completed_subtasks=1,
        project_id=project_id,
    )
    mock_emit_log.assert_any_call(
        task_id,
        "info",
        "All subtasks already complete; skipping checkout setup",
        project_id=project_id,
    )


@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts", return_value=TaskLaneConflictCheck())
@patch("app.tasks.autonomous.exec_modules.orchestrator.task_store")
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_subtasks_for_task")
@patch("app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator._has_active_task_checkpoint", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_task_checkout", return_value=object())
@patch("app.tasks.autonomous.exec_modules.orchestrator.setup_task_checkout", return_value="/tmp/checkout")
@patch("app.tasks.autonomous.exec_modules.orchestrator.handle_early_completion", return_value={"status": "completed"})
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_progress")
def test_execute_task_locked_recovers_existing_checkout_before_early_completion(
    mock_emit_progress: MagicMock,
    mock_emit_log: MagicMock,
    mock_early: MagicMock,
    mock_setup: MagicMock,
    mock_get_task_checkout: MagicMock,
    mock_has_checkpoint: MagicMock,
    mock_validate: MagicMock,
    mock_get_subtasks: MagicMock,
    mock_task_store: MagicMock,
    _mock_lane_conflicts: MagicMock,
) -> None:
    task_id = "task-complete"
    project_id = "summitflow"

    mock_task_store.get_task.return_value = {
        "id": task_id,
        "task_type": "refactor",
        "status": "completed",
    }
    mock_get_subtasks.return_value = [{"id": "s1", "subtask_id": "1.1", "passes": True}]

    result = start_execution(task_id, project_id)

    assert result == {"status": "completed"}
    mock_validate.assert_called_once_with(task_id, project_id)
    mock_has_checkpoint.assert_called_once_with(task_id, project_id)
    mock_get_task_checkout.assert_called_once_with(task_id, project_id)
    mock_setup.assert_called_once_with(task_id, project_id)
    mock_early.assert_called_once_with(task_id, project_id, 1, None)
    mock_emit_progress.assert_called_once_with(
        task_id,
        total_subtasks=1,
        completed_subtasks=1,
        project_id=project_id,
    )
    mock_emit_log.assert_any_call(
        task_id,
        "info",
        "All subtasks already complete; reusing existing task branch to recover residue before closeout",
        project_id=project_id,
    )


@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts", return_value=TaskLaneConflictCheck())
@patch("app.tasks.autonomous.exec_modules.orchestrator.task_store")
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_subtasks_for_task")
@patch("app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator.setup_task_checkout", return_value="/tmp/checkout")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_subtask_loop")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_progress")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_agent_feedback")
def test_execute_task_locked_skips_status_update_when_already_running(
    _mock_feedback: MagicMock,
    mock_emit_progress: MagicMock,
    mock_emit_log: MagicMock,
    mock_loop: MagicMock,
    mock_setup: MagicMock,
    mock_validate: MagicMock,
    mock_get_subtasks: MagicMock,
    mock_task_store: MagicMock,
    _mock_lane_conflicts: MagicMock,
) -> None:
    """When task is already running (claimed by dispatch), skip redundant status update."""
    task_id = "task-already-running"
    project_id = "monkey-fight"

    mock_task_store.get_task.return_value = {
        "id": task_id, "task_type": "task", "status": "running",
    }
    mock_get_subtasks.return_value = [{"id": "s1", "subtask_id": "1.1", "passes": False}]
    mock_loop.return_value = ([{"subtask_id": "1.1", "status": "passed"}], 1, None)

    with patch("app.tasks.autonomous.exec_modules.orchestrator.handle_successful_completion"):
        result = start_execution(task_id, project_id)

    assert result["status"] == "executed"
    for call in mock_task_store.update_task_status.call_args_list:
        assert call.args != (task_id, "running"), "Should not redundantly set status to running"


@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts", return_value=TaskLaneConflictCheck())
@patch("app.tasks.autonomous.exec_modules.orchestrator.task_store")
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_subtasks_for_task")
@patch("app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator.setup_task_checkout", return_value="/tmp/checkout")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_subtask_loop")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_progress")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_agent_feedback")
def test_execute_task_locked_sets_running_when_pending(
    _mock_feedback: MagicMock,
    mock_emit_progress: MagicMock,
    mock_emit_log: MagicMock,
    mock_loop: MagicMock,
    mock_setup: MagicMock,
    mock_validate: MagicMock,
    mock_get_subtasks: MagicMock,
    mock_task_store: MagicMock,
    _mock_lane_conflicts: MagicMock,
) -> None:
    """When task is pending (batch-pickup path without claim), status is set to running."""
    task_id = "task-pending"
    project_id = "monkey-fight"

    mock_task_store.get_task.return_value = {
        "id": task_id, "task_type": "task", "status": "pending",
    }
    mock_get_subtasks.return_value = [{"id": "s1", "subtask_id": "1.1", "passes": False}]
    mock_loop.return_value = ([{"subtask_id": "1.1", "status": "passed"}], 1, None)

    with patch("app.tasks.autonomous.exec_modules.orchestrator.handle_successful_completion"):
        result = start_execution(task_id, project_id)

    assert result["status"] == "executed"
    mock_task_store.update_task_status.assert_any_call(task_id, "running")


@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts", return_value=TaskLaneConflictCheck())
@patch("app.tasks.autonomous.exec_modules.orchestrator.task_store")
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_subtasks_for_task")
@patch("app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator.setup_task_checkout", return_value="/tmp/checkout")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_subtask_loop")
@patch("app.tasks.autonomous.exec_modules.orchestrator.handle_partial_completion")
@patch("app.tasks.autonomous.exec_modules.orchestrator.handle_failed_execution")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_progress")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_agent_feedback")
def test_execute_task_locked_skips_terminal_closeout_after_wind_down(
    mock_feedback: MagicMock,
    mock_emit_progress: MagicMock,
    mock_emit_log: MagicMock,
    mock_handle_failed: MagicMock,
    mock_handle_partial: MagicMock,
    mock_loop: MagicMock,
    mock_setup: MagicMock,
    mock_validate: MagicMock,
    mock_get_subtasks: MagicMock,
    mock_task_store: MagicMock,
    _mock_lane_conflicts: MagicMock,
) -> None:
    task_id = "task-paused"
    project_id = "summitflow"
    results = [
        {"subtask_id": "1.1", "status": "passed"},
        {"subtask_id": "1.2", "status": "failed", "error": "boom"},
    ]

    mock_task_store.get_task.return_value = {"id": task_id, "task_type": "bug", "status": "pending"}
    mock_get_subtasks.return_value = [
        {"id": "s1", "subtask_id": "1.1", "passes": False},
        {"id": "s2", "subtask_id": "1.2", "passes": False},
        {"id": "s3", "subtask_id": "1.3", "passes": False},
    ]
    mock_loop.return_value = (results, 2, WindDownState(paused=True, reason="max_iterations"))

    result = start_execution(task_id, project_id)

    assert result["status"] == "executed"
    mock_handle_partial.assert_not_called()
    mock_handle_failed.assert_not_called()
    mock_feedback.assert_called_once_with(task_id, "/tmp/checkout", project_id, results, agent_slug="coder")


@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts", return_value=TaskLaneConflictCheck())
@patch("app.tasks.autonomous.exec_modules.orchestrator.task_store")
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_subtasks_for_task")
@patch("app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator.setup_task_checkout", return_value="/tmp/checkout")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_subtask_loop")
@patch("app.tasks.autonomous.exec_modules.orchestrator.handle_partial_completion", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator.handle_failed_execution")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_progress")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_agent_feedback")
def test_execute_task_locked_allows_true_partial_completion_without_wind_down(
    mock_feedback: MagicMock,
    mock_emit_progress: MagicMock,
    mock_emit_log: MagicMock,
    mock_handle_failed: MagicMock,
    mock_handle_partial: MagicMock,
    mock_loop: MagicMock,
    mock_setup: MagicMock,
    mock_validate: MagicMock,
    mock_get_subtasks: MagicMock,
    mock_task_store: MagicMock,
    _mock_lane_conflicts: MagicMock,
) -> None:
    task_id = "task-partial"
    project_id = "summitflow"
    results = [
        {"subtask_id": "1.1", "status": "passed"},
        {"subtask_id": "1.2", "status": "failed", "error": "boom"},
    ]

    mock_task_store.get_task.return_value = {"id": task_id, "task_type": "bug", "status": "pending"}
    mock_get_subtasks.return_value = [
        {"id": "s1", "subtask_id": "1.1", "passes": False},
        {"id": "s2", "subtask_id": "1.2", "passes": False},
    ]
    mock_loop.return_value = (results, 2, None)

    result = start_execution(task_id, project_id)

    assert result["status"] == "executed"
    mock_handle_partial.assert_called_once()
    mock_handle_failed.assert_not_called()
    mock_feedback.assert_called_once()


@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_task_locked")
@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts")
def test_start_execution_skips_duplicate_same_task_lane(
    mock_lane_conflicts: MagicMock,
    mock_execute_locked: MagicMock,
    mock_emit_log: MagicMock,
) -> None:
    """Worker replays should not relaunch a second specialist session for the same task."""
    mock_lane_conflicts.return_value = TaskLaneConflictCheck(
        overlap_kind="same_task",
        disposition="block",
        owner_session_id="sess-existing",
        owner_location="checkout /tmp/task-123",
    )

    result = start_execution("task-123", "agent-hub")

    mock_execute_locked.assert_not_called()
    assert result == {
        "task_id": "task-123",
        "status": "already_running",
        "message": "Active task session already exists",
        "owner_session_id": "sess-existing",
    }
    assert mock_emit_log.call_args_list[-1].args[2] == (
        "Execution skipped: active task session already owned by session sess-existing"
    )


@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_task_locked", return_value={"status": "executed"})
@patch("app.tasks.autonomous.exec_modules.orchestrator._close_agent_hub_session", return_value=True)
@patch(
    "app.tasks.autonomous.exec_modules.orchestrator._fetch_agent_hub_session",
    return_value={
        "status": "completed",
        "live_activity": {"health": "completed", "lifecycle_state": "reapable", "reapable": True},
    },
)
@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts")
def test_start_execution_reclaims_stale_same_task_lane(
    mock_lane_conflicts: MagicMock,
    mock_fetch_session: MagicMock,
    mock_close_session: MagicMock,
    mock_execute_locked: MagicMock,
    mock_emit_log: MagicMock,
) -> None:
    mock_lane_conflicts.side_effect = [
        TaskLaneConflictCheck(
            overlap_kind="stale_same_task",
            disposition="reconcile",
            owner_session_id="sess-stale",
            owner_location="checkout /tmp/task-123",
        ),
        TaskLaneConflictCheck(),
    ]

    result = start_execution("task-123", "agent-hub")

    assert result == {"status": "executed"}
    mock_fetch_session.assert_called_once_with("sess-stale")
    mock_close_session.assert_called_once_with("sess-stale")
    mock_execute_locked.assert_called_once_with("task-123", "agent-hub", dispatch=None)
    assert any(
        call.args[2] == "Reclaiming stale same-task session sess-stale"
        for call in mock_emit_log.call_args_list
    )


@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_task_locked")
@patch("app.tasks.autonomous.exec_modules.orchestrator._close_agent_hub_session", return_value=False)
@patch(
    "app.tasks.autonomous.exec_modules.orchestrator._fetch_agent_hub_session",
    return_value={
        "status": "completed",
        "live_activity": {"health": "completed", "lifecycle_state": "reapable", "reapable": True},
    },
)
@patch("app.tasks.autonomous.exec_modules.orchestrator.check_task_lane_conflicts")
def test_start_execution_blocks_when_stale_same_task_reclaim_fails(
    mock_lane_conflicts: MagicMock,
    mock_fetch_session: MagicMock,
    mock_close_session: MagicMock,
    mock_execute_locked: MagicMock,
    mock_emit_log: MagicMock,
) -> None:
    mock_lane_conflicts.return_value = TaskLaneConflictCheck(
        overlap_kind="stale_same_task",
        disposition="reconcile",
        owner_session_id="sess-stale",
        owner_location="checkout /tmp/task-123",
    )

    result = start_execution("task-123", "agent-hub")

    mock_fetch_session.assert_called_once_with("sess-stale")
    mock_close_session.assert_called_once_with("sess-stale")
    mock_execute_locked.assert_not_called()
    assert result == {
        "task_id": "task-123",
        "status": "already_running",
        "message": "Stale task session requires reconciliation",
        "owner_session_id": "sess-stale",
    }
    assert any(
        call.args[2] == "Execution skipped: stale same-task session sess-stale could not be reclaimed"
        for call in mock_emit_log.call_args_list
    )


@pytest.mark.integration
def test_db_subtask_ordering(ensure_test_project: str, cleanup_task: Any) -> None:
    """Verify that subtasks are retrieved from the database in display_order."""
    task_id = f"test-ordering-task-{uuid.uuid4().hex[:8]}"
    cleanup_task(task_id)

    create_task(
        task_id=task_id,
        project_id=ensure_test_project,
        title="Test Ordering",
        description="Verify display order"
    )

    create_subtask(task_id, "2.1", "Third", display_order=2)
    create_subtask(task_id, "1.1", "First", display_order=0)
    create_subtask(task_id, "1.2", "Second", display_order=1)

    subtasks = get_subtasks_for_task(task_id)

    assert [s["subtask_id"] for s in subtasks] == ["1.1", "1.2", "2.1"]
    assert [s["display_order"] for s in subtasks] == [0, 1, 2]
