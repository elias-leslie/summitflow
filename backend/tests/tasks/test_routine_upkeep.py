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
    create_feedback = mocker.patch("app.tasks.autonomous.upkeep._create_feedback_tasks")
    mocker.patch("app.tasks.autonomous.upkeep.maintenance_store.record_maintenance_run")

    result = run_routine_upkeep("summitflow")

    assert result["tasks_created"] == 3
    run_refactors.assert_called_once_with("summitflow", 3)
    create_quality.assert_called_once_with("summitflow", 1)
    create_feedback.assert_not_called()


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
    create_feedback = mocker.patch("app.tasks.autonomous.upkeep._create_feedback_tasks")
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
    assert create_task.call_args.kwargs["autonomous"] is True
    assert create_task.call_args.kwargs["priority"] == 2
    assert create_task.call_args.kwargs["complexity"] == "SIMPLE"
    context = create_spirit.call_args.kwargs["context"]
    assert context["upkeep"]["source_key"] == "upkeep:quality:types:arg-type:backend/app/foo.py:42"
    assert context["upkeep"]["quality_result_id"] == 123
    assert context["files_to_modify"] == ["backend/app/foo.py"]
    assert create_spirit.call_args.kwargs["complexity"] == "SIMPLE"
    create_subtask.assert_called_once()
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
    mocker.patch("app.tasks.autonomous.upkeep_feedback.fetch_feedback_items", return_value=[feedback])
    mocker.patch("app.tasks.autonomous.upkeep_feedback.task_exists_for_upkeep_source", return_value=False)
    mocker.patch(
        "app.tasks.autonomous.upkeep_signals.task_store.create_task",
        return_value={"id": "task-feedback"},
    )
    create_spirit = mocker.patch("app.tasks.autonomous.upkeep_signals.create_task_spirit")
    mocker.patch("app.tasks.autonomous.upkeep_signals.create_single_subtask_with_steps")
    link_feedback = mocker.patch("app.tasks.autonomous.upkeep_feedback.link_feedback_task")

    created = upkeep._create_feedback_tasks("summitflow", limit=2)

    assert created == ["task-feedback"]
    context = create_spirit.call_args.kwargs["context"]
    assert context["upkeep"]["source_key"] == "upkeep:feedback:fb-123"
    assert context["upkeep"]["signal_type"] == "feedback"
    link_feedback.assert_called_once_with("fb-123", "task-feedback")


def test_create_feedback_task_prioritizes_tool_governance(mocker) -> None:
    from app.tasks.autonomous import upkeep

    feedback = {
        "id": "fb-governance",
        "component_id": "sf.quality",
        "feedback_type": "friction",
        "title": "Tool governance: missing quality gate",
        "description": "Expected st check.",
        "status": "open",
        "project_id": "summitflow",
        "vote_count": 1,
        "linked_task_id": None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    mocker.patch("app.tasks.autonomous.upkeep_feedback.fetch_feedback_items", return_value=[feedback])
    mocker.patch("app.tasks.autonomous.upkeep_feedback.task_exists_for_upkeep_source", return_value=False)
    create_task = mocker.patch(
        "app.tasks.autonomous.upkeep_signals.task_store.create_task",
        return_value={"id": "task-feedback"},
    )
    create_spirit = mocker.patch("app.tasks.autonomous.upkeep_signals.create_task_spirit")
    create_subtask = mocker.patch("app.tasks.autonomous.upkeep_signals.create_single_subtask_with_steps")
    mocker.patch("app.tasks.autonomous.upkeep_feedback.link_feedback_task")

    created = upkeep._create_feedback_tasks("summitflow", limit=2)

    assert created == ["task-feedback"]
    assert create_task.call_args.kwargs["priority"] == 1
    context = create_spirit.call_args.kwargs["context"]
    assert context["upkeep"]["tool_governance"] is True
    assert "backend/cli/commands/tools.py" in context["files_to_modify"]
    assert create_subtask.call_args.kwargs["description"] == "Resolve tool-governance feedback item fb-governance"
    steps = create_subtask.call_args.kwargs["steps"]
    assert steps[0]["description"].startswith("Verify the current governance signal")
    assert steps[2]["spec"]["verify_commands"] == ["st check --quick --changed-only"]


def test_create_feedback_task_replaces_stale_linked_task(mocker) -> None:
    from app.tasks.autonomous import upkeep

    feedback = {
        "id": "fb-123",
        "component_id": "sf.quality",
        "feedback_type": "friction",
        "title": "Quality gate missing",
        "description": "Expected st check.",
        "status": "open",
        "project_id": "summitflow",
        "vote_count": 1,
        "linked_task_id": "task-stale",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mocker.patch("app.tasks.autonomous.upkeep_feedback.fetch_feedback_items", return_value=[feedback])
    mocker.patch("app.tasks.autonomous.upkeep_feedback.task_exists_for_upkeep_source", return_value=False)
    mocker.patch("app.tasks.autonomous.upkeep_feedback.task_store.get_task", return_value=None)
    mocker.patch("app.tasks.autonomous.upkeep_feedback.get_task_spirit")
    mocker.patch(
        "app.tasks.autonomous.upkeep_signals.task_store.create_task",
        return_value={"id": "task-feedback"},
    )
    mocker.patch("app.tasks.autonomous.upkeep_signals.create_task_spirit")
    mocker.patch("app.tasks.autonomous.upkeep_signals.create_single_subtask_with_steps")
    link_feedback = mocker.patch("app.tasks.autonomous.upkeep_feedback.link_feedback_task")

    created = upkeep._create_feedback_tasks("summitflow", limit=2)

    assert created == ["task-feedback"]
    link_feedback.assert_called_once_with("fb-123", "task-feedback")


def test_create_feedback_task_keeps_valid_linked_task(mocker) -> None:
    from app.tasks.autonomous import upkeep

    feedback = {
        "id": "fb-123",
        "component_id": "sf.quality",
        "feedback_type": "friction",
        "title": "Quality gate missing",
        "description": "Expected st check.",
        "status": "open",
        "project_id": "summitflow",
        "vote_count": 1,
        "linked_task_id": "task-existing",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mocker.patch("app.tasks.autonomous.upkeep_feedback.fetch_feedback_items", return_value=[feedback])
    mocker.patch("app.tasks.autonomous.upkeep_feedback.task_exists_for_upkeep_source", return_value=False)
    mocker.patch(
        "app.tasks.autonomous.upkeep_feedback.task_store.get_task",
        return_value={"id": "task-existing", "project_id": "summitflow", "status": "pending"},
    )
    mocker.patch(
        "app.tasks.autonomous.upkeep_feedback.get_task_spirit",
        return_value={"context": {"upkeep": {"source_key": "upkeep:feedback:fb-123"}}},
    )
    create_task = mocker.patch("app.tasks.autonomous.upkeep_signals.task_store.create_task")
    link_feedback = mocker.patch("app.tasks.autonomous.upkeep_feedback.link_feedback_task")

    created = upkeep._create_feedback_tasks("summitflow", limit=2)

    assert created == []
    create_task.assert_not_called()
    link_feedback.assert_not_called()


def test_create_feedback_task_stays_in_current_project(mocker) -> None:
    from app.tasks.autonomous import upkeep

    feedback = {
        "id": "fb-456",
        "component_id": "st.search",
        "feedback_type": "friction",
        "title": "Search task created in wrong queue",
        "description": "This belongs with SummitFlow maintenance.",
        "status": "open",
        "project_id": "portfolio-ai",
        "vote_count": 1,
        "linked_task_id": None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    mocker.patch("app.tasks.autonomous.upkeep_feedback.fetch_feedback_items", return_value=[feedback])
    task_exists = mocker.patch("app.tasks.autonomous.upkeep_feedback.task_exists_for_upkeep_source", return_value=False)
    create_task = mocker.patch(
        "app.tasks.autonomous.upkeep_signals.task_store.create_task",
        return_value={"id": "task-feedback"},
    )
    mocker.patch("app.tasks.autonomous.upkeep_signals.create_task_spirit")
    mocker.patch("app.tasks.autonomous.upkeep_signals.create_single_subtask_with_steps")
    mocker.patch("app.tasks.autonomous.upkeep_feedback.link_feedback_task")

    created = upkeep._create_feedback_tasks("portfolio-ai", limit=2)

    assert created == ["task-feedback"]
    task_exists.assert_called_once_with("portfolio-ai", "upkeep:feedback:fb-456")
    assert create_task.call_args.kwargs["project_id"] == "portfolio-ai"


def test_task_exists_for_upkeep_source_uses_task_spirit_context(mocker) -> None:
    from app.tasks.autonomous.upkeep_signals import task_exists_for_upkeep_source

    cursor = MagicMock()
    cursor.fetchone.return_value = ("task-existing",)
    get_cursor = mocker.patch("app.tasks.autonomous.upkeep_signals.get_cursor")
    get_cursor.return_value.__enter__.return_value = cursor

    assert task_exists_for_upkeep_source("summitflow", "upkeep:quality:123") == "task-existing"

    sql_text = cursor.execute.call_args.args[0]
    assert "ts.context -> 'upkeep' ->> 'source_key'" in sql_text
    assert "completed" in sql_text
    assert "cancelled" in sql_text
