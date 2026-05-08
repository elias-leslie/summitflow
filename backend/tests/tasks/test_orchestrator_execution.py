from __future__ import annotations

from unittest.mock import MagicMock

from app.tasks.autonomous.exec_modules.orchestrator_execution import (
    execute_task_locked_impl,
    run_incomplete_subtasks,
)


def test_setup_failure_marks_running_task_failed() -> None:
    task_store = MagicMock()
    task_store.update_task_status.return_value = {"status": "failed"}

    project_path, results, wind_down_state, agent_override = run_incomplete_subtasks(
        "task-123",
        "agent-hub",
        [{"short_id": "1.1"}],
        1,
        0,
        prepare_execution=lambda *_args: (
            {"task_id": "task-123", "status": "failed", "error": "Pristine validation failed"},
            None,
            None,
            None,
        ),
        task_store=task_store,
        execute_subtask_loop=MagicMock(),
    )

    assert project_path == ""
    assert results[0]["error"] == "Pristine validation failed"
    assert wind_down_state is None
    assert agent_override is None
    task_store.update_task_status.assert_called_once_with(
        "task-123",
        "failed",
        error_message="Pristine validation failed",
    )


def test_completed_closeout_setup_failure_marks_task_failed() -> None:
    task_store = MagicMock()
    task_store.get_task.return_value = {"id": "task-123", "status": "running"}

    result = execute_task_locked_impl(
        "task-123",
        "agent-hub",
        dispatch=None,
        deps={
            "task_store": task_store,
            "emit_error": MagicMock(),
            "load_subtasks": lambda *_args: (None, [], 1, 1),
            "prepare_completed_task_closeout": lambda *_args: {
                "task_id": "task-123",
                "status": "failed",
                "reason": "task_branch_setup_failed",
                "error": "Task branch setup failed",
            },
            "handle_early_completion": MagicMock(),
        },
    )

    assert result["error"] == "Task branch setup failed"
    task_store.update_task_status.assert_called_once_with(
        "task-123",
        "failed",
        error_message="Task branch setup failed",
    )
