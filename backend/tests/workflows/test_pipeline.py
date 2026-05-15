from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, cast

import pytest


def test_dispatch_callback_raises_on_unknown_stage() -> None:
    from app.workflows.pipeline import _make_dispatch_callback

    dispatch = _make_dispatch_callback()

    with pytest.raises(ValueError, match="Unknown workflow stage: missing-stage"):
        dispatch("missing-stage", "task-123", "project-123")


async def _run_inline(func, *args, **kwargs):
    return func(*args, **kwargs)


async def _noop_async(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_execute_wf_excludes_current_preclaimed_task_from_concurrency_guard(monkeypatch) -> None:
    from app.workflows.models import TaskInput
    from app.workflows.pipeline import execute_wf

    seen_kwargs: dict[str, object] = {}

    monkeypatch.setattr("app.workflows.pipeline.asyncio.to_thread", _run_inline)
    monkeypatch.setattr(
        "app.storage.tasks.get_task",
        lambda _task_id: {"id": "task-177f0dec", "task_type": "refactor"},
    )

    def fake_validate(_project_id: str, _task_type: str | None = None, **kwargs: object) -> None:
        seen_kwargs.update(kwargs)
        return None

    monkeypatch.setattr("app.tasks.autonomous.pickup_guards.validate_autonomous_dispatch", fake_validate)
    monkeypatch.setattr(
        "app.tasks.autonomous.execution.start_execution",
        lambda task_id, project_id, dispatch=None: {"task_id": task_id, "project_id": project_id, "status": "executed"},
    )
    monkeypatch.setattr(
        "app.workflows.pipeline._drain_project_queue_after_execution",
        _noop_async,
    )

    runner = cast(Any, getattr(getattr(execute_wf, "_task", None), "fn", execute_wf))
    call = runner(
        TaskInput(task_id="task-177f0dec", project_id="agent-hub", manual_dispatch=True),
        None,
    )
    assert isinstance(call, Awaitable)
    result = cast(dict[str, Any], await call)

    assert seen_kwargs == {"require_enabled": False, "exclude_task_id": "task-177f0dec"}
    assert result["status"] == "executed"


@pytest.mark.asyncio
async def test_execute_wf_drains_queue_after_execution(monkeypatch) -> None:
    from app.workflows.models import TaskInput
    from app.workflows.pipeline import execute_wf

    drained: dict[str, object] = {}

    monkeypatch.setattr("app.workflows.pipeline.asyncio.to_thread", _run_inline)
    monkeypatch.setattr(
        "app.storage.tasks.get_task",
        lambda _task_id: {"id": "task-177f0dec", "task_type": "refactor"},
    )
    monkeypatch.setattr(
        "app.tasks.autonomous.pickup_guards.validate_autonomous_dispatch",
        lambda _project_id, _task_type=None, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.tasks.autonomous.execution.start_execution",
        lambda task_id, project_id, dispatch=None: {"task_id": task_id, "project_id": project_id, "status": "executed"},
    )

    async def fake_drain(project_id: str, *, manual_dispatch: bool) -> None:
        drained["project_id"] = project_id
        drained["manual_dispatch"] = manual_dispatch

    monkeypatch.setattr("app.workflows.pipeline._drain_project_queue_after_execution", fake_drain)

    runner = cast(Any, getattr(getattr(execute_wf, "_task", None), "fn", execute_wf))
    result = cast(
        dict[str, Any],
        await runner(TaskInput(task_id="task-177f0dec", project_id="agent-hub", manual_dispatch=True), None),
    )

    assert result["status"] == "executed"
    assert drained == {"project_id": "agent-hub", "manual_dispatch": True}


@pytest.mark.asyncio
async def test_execute_wf_releases_claim_when_guard_blocks(monkeypatch) -> None:
    from app.workflows.models import TaskInput
    from app.workflows.pipeline import execute_wf

    released: list[str] = []

    monkeypatch.setattr("app.workflows.pipeline.asyncio.to_thread", _run_inline)
    monkeypatch.setattr(
        "app.storage.tasks.get_task",
        lambda _task_id: {"id": "task-177f0dec", "task_type": "refactor"},
    )
    monkeypatch.setattr("app.storage.tasks.release_task", lambda task_id: released.append(task_id))
    monkeypatch.setattr(
        "app.tasks.autonomous.pickup_guards.validate_autonomous_dispatch",
        lambda _project_id, _task_type=None, **_kwargs: {"status": "concurrency_limit"},
    )

    runner = cast(Any, getattr(getattr(execute_wf, "_task", None), "fn", execute_wf))
    result = cast(
        dict[str, Any],
        await runner(TaskInput(task_id="task-177f0dec", project_id="agent-hub", manual_dispatch=True), None),
    )

    assert result["status"] == "concurrency_limit"
    assert released == ["task-177f0dec"]
