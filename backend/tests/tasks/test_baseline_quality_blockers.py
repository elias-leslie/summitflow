from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

from app.storage import task_dependencies
from app.storage import tasks as task_store
from app.storage.subtasks import get_subtasks_for_task
from app.storage.task_spirit import approve_plan, create_task_spirit, get_task_spirit
from app.tasks.autonomous.exec_modules.baseline_blockers import (
    BASELINE_QUALITY_MARKER,
    clear_project_quality_gate_blockers,
    ensure_quality_gate_blocker,
    is_baseline_quality_gate_task,
)
from app.tasks.autonomous.exec_modules.pristine import PristineCheckError
from app.tasks.autonomous.exec_modules.pristine_validation import validate_pristine_codebase


def _create_approved_task(
    project_id: str,
    cleanup_task: Callable[[str], None],
    *,
    title: str = "Blocked task",
) -> dict[str, Any]:
    task = task_store.create_task(project_id=project_id, title=title, task_type="refactor")
    cleanup_task(task["id"])
    create_task_spirit(
        task_id=task["id"],
        done_when=["All configured quality gates pass"],
        context={},
        complexity="SIMPLE",
    )
    approve_plan(task["id"], approved_by="test")
    return task


def test_quality_gate_blocker_resets_original_to_pending_and_adds_dependency(
    ensure_test_project: str,
    cleanup_task: Callable[[str], None],
) -> None:
    task = _create_approved_task(ensure_test_project, cleanup_task)
    claimed = task_store.claim_task(task["id"], "test-worker", lock_duration_minutes=60)
    assert claimed is not None

    blocker_id = ensure_quality_gate_blocker(
        task["id"],
        ensure_test_project,
        error_message="Codebase quality gates failed",
        output="TEST:FAIL:1|hint:===== 2 failed, 10 passed ======",
    )
    cleanup_task(blocker_id)

    updated = task_store.get_task(task["id"])
    assert updated is not None
    assert updated["status"] == "pending"
    assert updated["claimed_by"] is None
    assert updated["lock_expires_at"] is None
    assert blocker_id in updated["error_message"]

    deps = task_dependencies.get_dependencies(task["id"])
    assert [dep["depends_on_task_id"] for dep in deps] == [blocker_id]
    assert task_dependencies.is_blocked(task["id"]) is True
    assert any(item["id"] == task["id"] for item in task_store.list_blocked_tasks(ensure_test_project))

    assert is_baseline_quality_gate_task(blocker_id) is True
    spirit = get_task_spirit(blocker_id)
    assert spirit is not None
    assert spirit["context"]["upkeep"][BASELINE_QUALITY_MARKER] is True
    subtasks = get_subtasks_for_task(blocker_id, include_steps=True)
    assert len(subtasks) == 1
    assert subtasks[0]["steps_source"] == "plan_context"
    assert [step["description"] for step in subtasks[0]["steps"]] == [
        "Inspect st check output and referenced .dev-tools detail files to identify the current baseline failures",
        "Fix only the current baseline quality failures without broadening scope",
        "Verify the baseline quality gate is green",
    ]


def test_clear_project_quality_gate_blockers_unblocks_original_task(
    ensure_test_project: str,
    cleanup_task: Callable[[str], None],
) -> None:
    task = _create_approved_task(ensure_test_project, cleanup_task)
    blocker_id = ensure_quality_gate_blocker(
        task["id"],
        ensure_test_project,
        error_message="Codebase quality gates failed",
        output="TEST:FAIL:1|hint:===== 2 failed, 10 passed ======",
    )
    cleanup_task(blocker_id)
    assert task_dependencies.is_blocked(task["id"]) is True

    result = clear_project_quality_gate_blockers(ensure_test_project)

    assert result["deleted"] >= 1
    assert task_dependencies.is_blocked(task["id"]) is False


def test_validate_pristine_blocks_without_inline_self_heal(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_check(_project_id: str) -> None:
        raise PristineCheckError("Codebase quality gates failed", output="TEST:FAIL:1")

    def fake_ensure(task_id: str, project_id: str, **kwargs: object) -> str:
        seen.update({"task_id": task_id, "project_id": project_id, **kwargs})
        return "task-blocker"

    monkeypatch.setattr(
        "app.tasks.autonomous.exec_modules.pristine_validation.is_baseline_quality_gate_task",
        lambda _task_id: False,
    )
    monkeypatch.setattr(
        "app.tasks.autonomous.exec_modules.pristine_validation.check_pristine_codebase",
        fake_check,
    )
    monkeypatch.setattr(
        "app.tasks.autonomous.exec_modules.pristine_validation.ensure_quality_gate_blocker",
        fake_ensure,
    )
    monkeypatch.setattr(
        "app.tasks.autonomous.exec_modules.pristine_validation.emit_log",
        MagicMock(),
    )
    monkeypatch.setattr(
        "app.tasks.autonomous.exec_modules.pristine_validation.emit_error",
        MagicMock(),
    )

    assert validate_pristine_codebase("task-123", "agent-hub") is False
    assert seen == {
        "task_id": "task-123",
        "project_id": "agent-hub",
        "error_message": "Codebase quality gates failed",
        "output": "TEST:FAIL:1",
    }


def test_validate_pristine_skips_precheck_for_baseline_quality_task(monkeypatch) -> None:
    check = MagicMock()
    monkeypatch.setattr(
        "app.tasks.autonomous.exec_modules.pristine_validation.is_baseline_quality_gate_task",
        lambda _task_id: True,
    )
    monkeypatch.setattr(
        "app.tasks.autonomous.exec_modules.pristine_validation.check_pristine_codebase",
        check,
    )
    monkeypatch.setattr(
        "app.tasks.autonomous.exec_modules.pristine_validation.emit_log",
        MagicMock(),
    )

    assert validate_pristine_codebase("task-baseline", "agent-hub") is True
    check.assert_not_called()
