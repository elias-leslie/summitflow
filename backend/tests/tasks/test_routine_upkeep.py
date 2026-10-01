"""Tests for routine upkeep signal discovery and routing."""

from __future__ import annotations

from contextlib import contextmanager
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


def test_run_routine_upkeep_force_runs_even_when_disabled(mocker) -> None:
    """Manual `st autonomous upkeep` (force=True) bypasses the disabled schedule gate."""
    from app.tasks.autonomous.upkeep import RoutineUpkeepSettings, run_routine_upkeep

    mocker.patch(
        "app.tasks.autonomous.upkeep.get_routine_upkeep_settings",
        return_value=RoutineUpkeepSettings(enabled=False, batch_limit=5),
    )
    is_due = mocker.patch("app.tasks.autonomous.upkeep._is_due", return_value=False)
    mocker.patch("app.tasks.autonomous.upkeep._routine_upkeep_lock", return_value=_acquired_lock())
    run_refactors = mocker.patch(
        "app.tasks.autonomous.upkeep._run_refactor_source",
        return_value={"created_count": 1, "retired_count": 0, "scanned_count": 1},
    )
    mocker.patch("app.tasks.autonomous.upkeep._create_quality_failure_tasks", return_value=[])
    mocker.patch("app.tasks.autonomous.upkeep.maintenance_store.record_maintenance_run")

    result = run_routine_upkeep("summitflow", force=True)

    # Disabled schedule did not short-circuit; the due-interval was never consulted.
    assert result["status"] == "completed"
    assert result["tasks_created"] == 1
    run_refactors.assert_called_once_with("summitflow", 5)
    is_due.assert_not_called()


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
    record_run = mocker.patch("app.tasks.autonomous.upkeep.maintenance_store.record_maintenance_run")

    result = run_routine_upkeep("summitflow")

    assert result["status"] == "completed"
    assert result["tasks_created"] == 0
    assert result["dispatch"]["dispatched"] == 0
    assert result["dispatch"]["message"] == "discovery_only"
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
    mocker.patch("app.tasks.autonomous.upkeep.maintenance_store.record_maintenance_run")

    result = run_routine_upkeep("summitflow")

    assert result["tasks_created"] == 3
    run_refactors.assert_called_once_with("summitflow", 3)
    create_quality.assert_called_once_with("summitflow", 1)


def test_upkeep_refactor_source_uses_existing_scan_index(mocker) -> None:
    from app.tasks.autonomous import upkeep

    regenerate = mocker.patch(
        "app.tasks.autonomous.upkeep.regenerate_refactor_tasks_impl",
        return_value={"created_count": 0},
    )

    upkeep._run_refactor_source("summitflow", 3)

    regenerate.assert_called_once_with("summitflow", create_limit=3, refresh_scan=False)


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
    mocker.patch("app.tasks.autonomous.upkeep.maintenance_store.record_maintenance_run")

    result = run_routine_upkeep("summitflow")

    assert result["tasks_created"] == 2
    create_quality.assert_called_once_with("summitflow", 2)


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
    mocker.patch("app.tasks.autonomous.upkeep_quality.list_unfixed_quality_results", return_value=[quality_result])
    mocker.patch("app.tasks.autonomous.upkeep_quality.task_exists_for_upkeep_source", return_value=False)
    create_task = mocker.patch(
        "app.tasks.autonomous.upkeep_signals.task_store.create_task",
        return_value={"id": "task-quality"},
    )
    create_spirit = mocker.patch("app.tasks.autonomous.upkeep_signals.create_task_spirit")
    create_subtask = mocker.patch("app.tasks.autonomous.upkeep_signals.create_single_subtask_with_steps")
    mark_escalated = mocker.patch("app.tasks.autonomous.upkeep_quality.mark_quality_escalated")

    created = upkeep._create_quality_failure_tasks("summitflow", limit=3)

    assert created == ["task-quality"]
    assert create_task.call_args.kwargs["execution_mode"] == "autonomous"
    assert create_task.call_args.kwargs["priority"] == 2
    assert create_task.call_args.kwargs["complexity"] == "SIMPLE"
    context = create_spirit.call_args.kwargs["context"]
    assert context["upkeep"]["source_key"] == "upkeep:quality:types:arg-type:backend/app/foo.py:42"
    assert context["upkeep"]["quality_result_id"] == 123
    assert context["files_to_modify"] == ["backend/app/foo.py"]
    assert create_spirit.call_args.kwargs["complexity"] == "SIMPLE"
    create_subtask.assert_called_once()
    assert create_subtask.call_args.kwargs["subtask_type"] == "bug-fix"
    mark_escalated.assert_called_once_with(123, "task-quality")


def test_create_quality_failure_task_skips_unactionable_project_level_failures(mocker) -> None:
    from app.tasks.autonomous import upkeep

    quality_result = {
        "id": 123,
        "project_id": "summitflow",
        "check_type": "types",
        "check_name": "mypy",
        "status": "fail",
        "error_message": None,
        "file_path": None,
        "line_number": None,
        "escalation_task_id": None,
    }
    mocker.patch("app.tasks.autonomous.upkeep_quality.list_unfixed_quality_results", return_value=[quality_result])
    create_task = mocker.patch("app.tasks.autonomous.upkeep_signals.task_store.create_task")
    mark_escalated = mocker.patch("app.tasks.autonomous.upkeep_quality.mark_quality_escalated")

    created = upkeep._create_quality_failure_tasks("summitflow", limit=3)

    assert created == []
    create_task.assert_not_called()
    mark_escalated.assert_not_called()


def test_quality_failure_task_dedupes_by_stable_signal_not_result_id(mocker) -> None:
    from app.tasks.autonomous import upkeep

    quality_result = {
        "id": 123,
        "project_id": "summitflow",
        "check_type": "types",
        "check_name": "assignment",
        "status": "fail",
        "error_message": "bad type",
        "file_path": "backend/app/foo.py",
        "line_number": 42,
        "escalation_task_id": None,
    }
    mocker.patch("app.tasks.autonomous.upkeep_quality.list_unfixed_quality_results", return_value=[quality_result])
    task_exists = mocker.patch(
        "app.tasks.autonomous.upkeep_quality.task_exists_for_upkeep_source",
        return_value="task-existing",
    )
    create_task = mocker.patch("app.tasks.autonomous.upkeep_signals.task_store.create_task")
    mark_escalated = mocker.patch("app.tasks.autonomous.upkeep_quality.mark_quality_escalated")

    created = upkeep._create_quality_failure_tasks("summitflow", limit=3)

    assert created == []
    task_exists.assert_called_once_with(
        "summitflow",
        "upkeep:quality:types:assignment:backend/app/foo.py:42",
    )
    create_task.assert_not_called()
    mark_escalated.assert_not_called()


def test_feedback_compatibility_entrypoints_never_create_work(mocker) -> None:
    from app.tasks.autonomous.upkeep_feedback import create_feedback_tasks, feedback_task_from_item

    create = mocker.patch("app.tasks.autonomous.upkeep_signals.task_store.create_task")
    approve = mocker.patch("app.tasks.autonomous.upkeep_signals.approve_plan")
    for feedback_type in ("friction", "idea", "improvement", "praise"):
        assert feedback_task_from_item("summitflow", {"id": "item", "feedback_type": feedback_type,
                                                    "vote_count": 999, "status": "acknowledged"}) is None
    assert create_feedback_tasks("summitflow", 200) == []
    create.assert_not_called()
    approve.assert_not_called()


def test_scheduled_and_forced_upkeep_cannot_promote_feedback(mocker) -> None:
    from app.tasks.autonomous.upkeep import RoutineUpkeepSettings, run_routine_upkeep
    from app.tasks.autonomous.upkeep_constants import SOURCES

    assert "feedback" not in SOURCES
    mocker.patch("app.tasks.autonomous.upkeep.get_routine_upkeep_settings",
                 return_value=RoutineUpkeepSettings(enabled=True))
    mocker.patch("app.tasks.autonomous.upkeep._is_due", return_value=True)
    mocker.patch("app.tasks.autonomous.upkeep._run_refactor_source", return_value={"created_count": 0})
    mocker.patch("app.tasks.autonomous.upkeep._create_quality_failure_tasks", return_value=[])
    mocker.patch("app.tasks.autonomous.upkeep.maintenance_store.record_maintenance_run")
    create = mocker.patch("app.tasks.autonomous.upkeep_signals.task_store.create_task")
    approve = mocker.patch("app.tasks.autonomous.upkeep_signals.approve_plan")
    dispatch = MagicMock()
    for force in (False, True):
        mocker.patch("app.tasks.autonomous.upkeep._routine_upkeep_lock", return_value=_acquired_lock())
        result = run_routine_upkeep("summitflow", dispatch=dispatch, force=force)
        assert result["tasks_created"] == 0
        assert result["dispatch"]["dispatched"] == 0
    create.assert_not_called()
    approve.assert_not_called()
    dispatch.assert_not_called()


def test_automatic_pickup_excludes_legacy_generated_feedback(mocker) -> None:
    from app.tasks.autonomous.pickup_queries import get_queued_autonomous_tasks

    cursor = MagicMock()
    cursor.fetchall.return_value = []
    manager = MagicMock()
    manager.__enter__.return_value = cursor
    mocker.patch("app.tasks.autonomous.pickup_queries.get_cursor", return_value=manager)
    mocker.patch("app.tasks.autonomous.pickup_queries.get_allowed_external_origins", return_value=None)
    assert get_queued_autonomous_tasks("summitflow") == []
    query = cursor.execute.call_args.args[0]
    assert "NOT ('auto-generated' = ANY(labels) AND 'feedback' = ANY(labels))" in query
    assert "ts.context -> 'upkeep' ->> 'signal_type' = 'feedback'" in query
