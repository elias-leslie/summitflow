"""Tests for routine upkeep signal discovery and routing."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock


@contextmanager
def _acquired_lock() -> Any:
    yield True


@contextmanager
def _blocked_lock() -> Any:
    yield False


def test_run_routine_upkeep_skips_disabled_without_history(mocker) -> None:
    from app.tasks.autonomous.upkeep import RoutineUpkeepSettings, run_routine_upkeep

    mocker.patch(
        "app.tasks.autonomous.upkeep.get_routine_upkeep_settings",
        return_value=RoutineUpkeepSettings(enabled=False),
    )
    record_run = mocker.patch("app.tasks.autonomous.upkeep.maintenance_store.record_maintenance_run")

    result = run_routine_upkeep("summitflow")

    assert result["status"] == "disabled"
    assert result["project_id"] == "summitflow"
    record_run.assert_not_called()


def test_run_routine_upkeep_records_completed_no_work(mocker) -> None:
    from app.tasks.autonomous.upkeep import RoutineUpkeepSettings, run_routine_upkeep

    mocker.patch(
        "app.tasks.autonomous.upkeep.get_routine_upkeep_settings",
        return_value=RoutineUpkeepSettings(enabled=True, batch_limit=5),
    )
    mocker.patch("app.tasks.autonomous.upkeep._is_due", return_value=True)
    mocker.patch("app.tasks.autonomous.upkeep._routine_upkeep_lock", return_value=_acquired_lock())
    mocker.patch(
        "app.tasks.autonomous.upkeep.regenerate_refactor_tasks_impl",
        return_value={"created_count": 0, "retired_count": 0, "scanned_count": 0},
    )
    mocker.patch("app.tasks.autonomous.upkeep._create_quality_failure_tasks", return_value=[])
    mocker.patch("app.tasks.autonomous.upkeep._create_feedback_tasks", return_value=[])
    mocker.patch(
        "app.tasks.autonomous.upkeep.autonomous_work_pickup",
        return_value={"project_id": "summitflow", "dispatched": 0, "message": "No tasks in queue"},
    )
    record_run = mocker.patch("app.tasks.autonomous.upkeep.maintenance_store.record_maintenance_run")

    result = run_routine_upkeep("summitflow")

    assert result["status"] == "completed"
    assert result["tasks_created"] == 0
    assert result["dispatch"]["dispatched"] == 0
    record_run.assert_called_once()
    assert record_run.call_args.args[:2] == ("routine_upkeep", "completed")
    assert record_run.call_args.kwargs["summary"]["outcome"] == "completed"


def test_run_routine_upkeep_reports_lock_contention(mocker) -> None:
    from app.tasks.autonomous.upkeep import RoutineUpkeepSettings, run_routine_upkeep

    mocker.patch(
        "app.tasks.autonomous.upkeep.get_routine_upkeep_settings",
        return_value=RoutineUpkeepSettings(enabled=True),
    )
    mocker.patch("app.tasks.autonomous.upkeep._is_due", return_value=True)
    mocker.patch("app.tasks.autonomous.upkeep._routine_upkeep_lock", return_value=_blocked_lock())
    record_run = mocker.patch("app.tasks.autonomous.upkeep.maintenance_store.record_maintenance_run")

    result = run_routine_upkeep("summitflow")

    assert result["status"] == "blocked"
    assert result["reason"] == "already_running"
    record_run.assert_called_once()
    assert record_run.call_args.args[:2] == ("routine_upkeep", "blocked")


def test_run_routine_upkeep_counts_refactors_against_batch_limit(mocker) -> None:
    from app.tasks.autonomous.upkeep import RoutineUpkeepSettings, run_routine_upkeep

    mocker.patch(
        "app.tasks.autonomous.upkeep.get_routine_upkeep_settings",
        return_value=RoutineUpkeepSettings(enabled=True, batch_limit=3),
    )
    mocker.patch("app.tasks.autonomous.upkeep._is_due", return_value=True)
    mocker.patch("app.tasks.autonomous.upkeep._routine_upkeep_lock", return_value=_acquired_lock())
    run_refactors = mocker.patch(
        "app.tasks.autonomous.upkeep._run_refactor_source",
        return_value={"created_count": 2, "retired_count": 0, "scanned_count": 4},
    )
    create_quality = mocker.patch(
        "app.tasks.autonomous.upkeep._create_quality_failure_tasks",
        return_value=["task-quality"],
    )
    create_feedback = mocker.patch("app.tasks.autonomous.upkeep._create_feedback_tasks")
    mocker.patch(
        "app.tasks.autonomous.upkeep.autonomous_work_pickup",
        return_value={"project_id": "summitflow", "dispatched": 0},
    )
    mocker.patch("app.tasks.autonomous.upkeep.maintenance_store.record_maintenance_run")

    result = run_routine_upkeep("summitflow")

    assert result["tasks_created"] == 3
    run_refactors.assert_called_once_with("summitflow", 3)
    create_quality.assert_called_once_with("summitflow", 1)
    create_feedback.assert_not_called()


def test_run_routine_upkeep_counts_quality_against_daily_budget(mocker) -> None:
    from app.tasks.autonomous.upkeep import RoutineUpkeepSettings, run_routine_upkeep

    mocker.patch(
        "app.tasks.autonomous.upkeep.get_routine_upkeep_settings",
        return_value=RoutineUpkeepSettings(enabled=True, batch_limit=5),
    )
    mocker.patch("app.tasks.autonomous.upkeep._is_due", return_value=True)
    mocker.patch("app.tasks.autonomous.upkeep._routine_upkeep_lock", return_value=_acquired_lock())
    mocker.patch("app.tasks.autonomous.upkeep._daily_budget_remaining", return_value=2)
    mocker.patch(
        "app.tasks.autonomous.upkeep._run_refactor_source",
        return_value={"created_count": 0, "retired_count": 0, "scanned_count": 0},
    )
    create_quality = mocker.patch(
        "app.tasks.autonomous.upkeep._create_quality_failure_tasks",
        return_value=["task-quality-1", "task-quality-2"],
    )
    create_feedback = mocker.patch("app.tasks.autonomous.upkeep._create_feedback_tasks")
    mocker.patch(
        "app.tasks.autonomous.upkeep.autonomous_work_pickup",
        return_value={"project_id": "summitflow", "dispatched": 0},
    )
    mocker.patch("app.tasks.autonomous.upkeep.maintenance_store.record_maintenance_run")

    result = run_routine_upkeep("summitflow")

    assert result["tasks_created"] == 2
    create_quality.assert_called_once_with("summitflow", 2)
    create_feedback.assert_not_called()


def test_create_quality_failure_task_uses_source_key_and_marks_escalated(mocker) -> None:
    from app.tasks.autonomous import upkeep

    quality_result = {
        "id": 123,
        "project_id": "summitflow",
        "check_type": "types",
        "check_name": "arg-type",
        "status": "fail",
        "error_message": "bad type",
        "file_path": "backend/app/foo.py",
        "line_number": 42,
        "escalation_task_id": None,
    }
    mocker.patch("app.tasks.autonomous.upkeep._list_unfixed_quality_results", return_value=[quality_result])
    mocker.patch("app.tasks.autonomous.upkeep.task_exists_for_upkeep_source", return_value=False)
    create_task = mocker.patch(
        "app.tasks.autonomous.upkeep.task_store.create_task",
        return_value={"id": "task-quality"},
    )
    create_spirit = mocker.patch("app.tasks.autonomous.upkeep.create_task_spirit")
    create_subtask = mocker.patch("app.tasks.autonomous.upkeep.create_single_subtask_with_steps")
    mark_escalated = mocker.patch("app.tasks.autonomous.upkeep._mark_quality_escalated")

    created = upkeep._create_quality_failure_tasks("summitflow", limit=3)

    assert created == ["task-quality"]
    assert create_task.call_args.kwargs["execution_mode"] == "autonomous"
    assert create_task.call_args.kwargs["autonomous"] is True
    context = create_spirit.call_args.kwargs["context"]
    assert context["upkeep"]["source_key"] == "upkeep:quality:123"
    assert context["files_to_modify"] == ["backend/app/foo.py"]
    create_subtask.assert_called_once()
    mark_escalated.assert_called_once_with(123, "task-quality")


def test_create_feedback_task_links_agent_hub_item(mocker) -> None:
    from app.tasks.autonomous import upkeep

    feedback = {
        "id": "fb-123",
        "component_id": "sf.cli",
        "feedback_type": "friction",
        "title": "CLI output confusing",
        "description": "The command output is hard to interpret.",
        "status": "open",
        "project_id": "summitflow",
        "vote_count": 2,
        "linked_task_id": None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    mocker.patch("app.tasks.autonomous.upkeep._fetch_feedback_items", return_value=[feedback])
    mocker.patch("app.tasks.autonomous.upkeep.task_exists_for_upkeep_source", return_value=False)
    mocker.patch(
        "app.tasks.autonomous.upkeep.task_store.create_task",
        return_value={"id": "task-feedback"},
    )
    create_spirit = mocker.patch("app.tasks.autonomous.upkeep.create_task_spirit")
    mocker.patch("app.tasks.autonomous.upkeep.create_single_subtask_with_steps")
    link_feedback = mocker.patch("app.tasks.autonomous.upkeep._link_feedback_task")

    created = upkeep._create_feedback_tasks("summitflow", limit=2)

    assert created == ["task-feedback"]
    context = create_spirit.call_args.kwargs["context"]
    assert context["upkeep"]["source_key"] == "upkeep:feedback:fb-123"
    assert context["upkeep"]["signal_type"] == "feedback"
    link_feedback.assert_called_once_with("fb-123", "task-feedback")


def test_task_exists_for_upkeep_source_uses_task_spirit_context(mocker) -> None:
    from app.tasks.autonomous.upkeep import task_exists_for_upkeep_source

    cursor = MagicMock()
    cursor.fetchone.return_value = ("task-existing",)
    get_cursor = mocker.patch("app.tasks.autonomous.upkeep.get_cursor")
    get_cursor.return_value.__enter__.return_value = cursor

    assert task_exists_for_upkeep_source("summitflow", "upkeep:quality:123") == "task-existing"

    sql_text = cursor.execute.call_args.args[0]
    assert "ts.context -> 'upkeep' ->> 'source_key'" in sql_text
    assert "completed" in sql_text
    assert "cancelled" in sql_text
