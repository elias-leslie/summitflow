"""Tests for sequential subtask execution."""

from __future__ import annotations

from unittest.mock import patch

from app.tasks.autonomous.exec_modules.execution_loop import execute_subtask_loop
from app.tasks.autonomous.exec_modules.interruption import ExecutionInterrupted
from app.tasks.autonomous.exec_modules.session import WindDownState


def test_subtask_execution_stops_at_max_iterations() -> None:
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
        "app.tasks.autonomous.exec_modules.execution_loop.assert_task_runnable",
    ), patch(
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
    mock_wind_down.assert_called_once()


def test_subtask_execution_continues_after_failures() -> None:
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

    assert [result["status"] for result in results] == ["passed", "failed", "passed"]
    assert completed_count == 3
    assert wind_down_state is None
    assert mock_execute.call_count == 3


def test_subtask_execution_winds_down_when_task_is_paused() -> None:
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
    mock_wind_down.assert_called_once_with(task_id, [], subtasks, "task_status=paused")


def test_subtask_execution_orders_incomplete_work_by_dependencies() -> None:
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
