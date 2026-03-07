"""Integration tests for sequential subtask execution."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.storage.subtasks import create_subtask, get_subtasks_for_task
from app.storage.tasks import create_task
from app.tasks.autonomous.exec_modules.execution_loop import execute_subtask_loop
from app.tasks.autonomous.exec_modules.interruption import ExecutionInterrupted
from app.tasks.autonomous.exec_modules.orchestrator import start_execution


def test_subtask_execution_order_sequential() -> None:
    """Verify that subtasks are executed in the correct sequential order in the execution loop."""
    task_id = "test-sequential-task"
    project_id = "test-project"
    project_path = "/tmp/test-project"

    # Subtasks in a specific order
    subtasks = [
        {"subtask_id": "1.1", "description": "First subtask"},
        {"subtask_id": "1.2", "description": "Second subtask"},
        {"subtask_id": "2.1", "description": "Third subtask"},
        {"subtask_id": "2.2", "description": "Fourth subtask"},
    ]

    executed_ids = []

    def mock_execute(
        task_id: str,
        subtask: dict[str, Any],
        project_id: str,
        issue_counts: dict[str, int],
        task_type: str | None = None,
        agent_override: str | None = None,
        tier_preference: str | None = None,
    ) -> dict[str, Any]:
        executed_ids.append(subtask["subtask_id"])
        return {
            "subtask_id": subtask["subtask_id"],
            "status": "passed",
        }

    # Patch dependencies to avoid real side effects
    with patch("app.tasks.autonomous.exec_modules.execution_loop.execute_subtask", side_effect=mock_execute), \
         patch("app.tasks.autonomous.exec_modules.execution_loop.assert_task_runnable"), \
         patch("app.tasks.autonomous.exec_modules.execution_loop.emit_progress"), \
         patch("app.tasks.autonomous.exec_modules.execution_loop.emit_log"), \
         patch("app.tasks.autonomous.exec_modules.execution_loop.has_uncommitted_changes", return_value=False):

        results, completed_count = execute_subtask_loop(
            task_id=task_id,
            project_id=project_id,
            project_path=project_path,
            incomplete_subtasks=subtasks,
            total_subtasks=len(subtasks),
            completed_count=0,
            task_type=None,
            agent_override=None
        )

    # Verify order of execution
    assert executed_ids == ["1.1", "1.2", "2.1", "2.2"], "Subtasks were not executed in sequential order"
    assert len(results) == 4
    assert completed_count == 4
    assert all(r["status"] == "passed" for r in results)


def test_subtask_execution_stops_on_failure_when_orchestrator_decides() -> None:
    """Verify that execution stops when a subtask fails and the failure handler returns False."""
    task_id = "test-failure-task"
    project_id = "test-project"
    project_path = "/tmp/test-project"

    subtasks = [
        {"subtask_id": "1.1", "description": "First"},
        {"subtask_id": "1.2", "description": "Second (fails)"},
        {"subtask_id": "1.3", "description": "Third"},
    ]

    executed_ids = []

    def mock_execute(
        task_id: str,
        subtask: dict[str, Any],
        project_id: str,
        issue_counts: dict[str, int],
        task_type: str | None = None,
        agent_override: str | None = None,
        tier_preference: str | None = None,
    ) -> dict[str, Any]:
        executed_ids.append(subtask["subtask_id"])
        if "fails" in subtask["description"]:
            return {"subtask_id": subtask["subtask_id"], "status": "failed", "issue_id": "test-failure"}
        return {"subtask_id": subtask["subtask_id"], "status": "passed"}

    # We need to patch the internal _handle_subtask_failure in execution_loop module
    with patch("app.tasks.autonomous.exec_modules.execution_loop.execute_subtask", side_effect=mock_execute), \
         patch("app.tasks.autonomous.exec_modules.execution_loop.assert_task_runnable"), \
         patch("app.tasks.autonomous.exec_modules.execution_loop.emit_progress"), \
         patch("app.tasks.autonomous.exec_modules.execution_loop.emit_log"), \
         patch("app.tasks.autonomous.exec_modules.execution_loop.has_uncommitted_changes", return_value=False), \
         patch("app.tasks.autonomous.exec_modules.execution_loop._handle_subtask_failure", return_value=False):

        results, _ = execute_subtask_loop(
            task_id=task_id,
            project_id=project_id,
            project_path=project_path,
            incomplete_subtasks=subtasks,
            total_subtasks=len(subtasks),
            completed_count=0,
            task_type=None,
            agent_override=None
        )

    # Should stop after 1.2 because _handle_subtask_failure returned False
    assert executed_ids == ["1.1", "1.2"]
    assert len(results) == 2
    assert results[1]["status"] == "failed"


def test_subtask_execution_continues_on_failure_when_orchestrator_decides() -> None:
    """Verify that execution continues when a subtask fails but the failure handler returns True."""
    task_id = "test-failure-continue-task"
    project_id = "test-project"
    project_path = "/tmp/test-project"

    subtasks = [
        {"subtask_id": "1.1", "description": "First"},
        {"subtask_id": "1.2", "description": "Second (fails)"},
        {"subtask_id": "1.3", "description": "Third"},
    ]

    executed_ids = []

    def mock_execute(
        task_id: str,
        subtask: dict[str, Any],
        project_id: str,
        issue_counts: dict[str, int],
        task_type: str | None = None,
        agent_override: str | None = None,
        tier_preference: str | None = None,
    ) -> dict[str, Any]:
        executed_ids.append(subtask["subtask_id"])
        if "fails" in subtask["description"]:
            return {"subtask_id": subtask["subtask_id"], "status": "failed", "issue_id": "test-failure"}
        return {"subtask_id": subtask["subtask_id"], "status": "passed"}

    # We need to patch the internal _handle_subtask_failure in execution_loop module
    with patch("app.tasks.autonomous.exec_modules.execution_loop.execute_subtask", side_effect=mock_execute), \
         patch("app.tasks.autonomous.exec_modules.execution_loop.assert_task_runnable"), \
         patch("app.tasks.autonomous.exec_modules.execution_loop.emit_progress"), \
         patch("app.tasks.autonomous.exec_modules.execution_loop.emit_log"), \
         patch("app.tasks.autonomous.exec_modules.execution_loop.has_uncommitted_changes", return_value=False), \
         patch("app.tasks.autonomous.exec_modules.execution_loop._handle_subtask_failure", return_value=True):

        results, _ = execute_subtask_loop(
            task_id=task_id,
            project_id=project_id,
            project_path=project_path,
            incomplete_subtasks=subtasks,
            total_subtasks=len(subtasks),
            completed_count=0,
            task_type=None,
            agent_override=None
        )

    # Should NOT stop after 1.2 because _handle_subtask_failure returned True
    assert executed_ids == ["1.1", "1.2", "1.3"]
    assert len(results) == 3
    assert results[1]["status"] == "failed"
    assert results[2]["status"] == "passed"


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
        "app.tasks.autonomous.exec_modules.execution_loop.wind_down"
    ) as mock_wind_down, patch(
        "app.tasks.autonomous.exec_modules.execution_loop.emit_log"
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop.has_uncommitted_changes",
        return_value=False,
    ), patch(
        "app.tasks.autonomous.exec_modules.execution_loop._check_health_or_wait",
        return_value=True,
    ):
        results, completed_count = execute_subtask_loop(
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
    mock_wind_down.assert_called_once_with(
        task_id,
        [],
        subtasks,
        "task_status=paused",
    )


@patch("app.tasks.autonomous.exec_modules.orchestrator.task_store")
@patch("app.tasks.autonomous.exec_modules.orchestrator.get_subtasks_for_task")
@patch("app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase", return_value=True)
@patch("app.tasks.autonomous.exec_modules.orchestrator.setup_worktree", return_value="/tmp/worktree")
@patch("app.tasks.autonomous.exec_modules.orchestrator.execute_subtask_loop")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_log")
@patch("app.tasks.autonomous.exec_modules.orchestrator.emit_progress")
def test_start_execution_orchestration_flow(
    mock_emit_progress: MagicMock,
    mock_emit_log: MagicMock,
    mock_loop: MagicMock,
    mock_setup: MagicMock,
    mock_validate: MagicMock,
    mock_get_subtasks: MagicMock,
    mock_task_store: MagicMock,
) -> None:
    """Verify that start_execution correctly orchestrates subtask execution."""
    task_id = "task-123"
    project_id = "proj-123"

    mock_task_store.get_task.return_value = {"id": task_id, "task_type": "task"}

    # Subtasks from storage (already ordered by display_order)
    subtasks = [
        {"id": "s1", "subtask_id": "1.1", "passes": False},
        {"id": "s2", "subtask_id": "1.2", "passes": False},
        {"id": "s3", "subtask_id": "2.1", "passes": True},  # Already passed
    ]
    mock_get_subtasks.return_value = subtasks

    mock_loop.return_value = (
        [{"subtask_id": "1.1", "status": "passed"}, {"subtask_id": "1.2", "status": "passed"}],
        2
    )

    with patch("app.tasks.autonomous.exec_modules.orchestrator.handle_successful_completion"):
        result = start_execution(task_id, project_id)

    assert result["status"] == "executed"
    mock_loop.assert_called_once()

    # Verify it passed only INCOMPLETE subtasks to the loop
    args = mock_loop.call_args[0]
    passed_incomplete_subtasks = args[3]
    assert len(passed_incomplete_subtasks) == 2
    assert passed_incomplete_subtasks[0]["subtask_id"] == "1.1"
    assert passed_incomplete_subtasks[1]["subtask_id"] == "1.2"

    # Verify task status was updated to running
    mock_task_store.update_task_status.assert_called_with(task_id, "running")


@pytest.mark.integration
def test_db_subtask_ordering(ensure_test_project: str, cleanup_task: Any) -> None:
    """Verify that subtasks are retrieved from the database in display_order."""
    task_id = "test-ordering-task"
    cleanup_task(task_id)

    create_task(
        task_id=task_id,
        project_id=ensure_test_project,
        title="Test Ordering",
        description="Verify display order"
    )

    # Create subtasks out of order
    create_subtask(task_id, "2.1", "Third", display_order=2)
    create_subtask(task_id, "1.1", "First", display_order=0)
    create_subtask(task_id, "1.2", "Second", display_order=1)

    subtasks = get_subtasks_for_task(task_id)

    assert [s["subtask_id"] for s in subtasks] == ["1.1", "1.2", "2.1"]
    assert [s["display_order"] for s in subtasks] == [0, 1, 2]
