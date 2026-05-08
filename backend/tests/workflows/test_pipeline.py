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

    call = execute_wf._task.fn(
        TaskInput(task_id="task-177f0dec", project_id="agent-hub", manual_dispatch=True),
        None,
    )
    assert isinstance(call, Awaitable)
    result = cast(dict[str, Any], await call)

    assert seen_kwargs == {"require_enabled": False, "exclude_task_id": "task-177f0dec"}
    assert result["status"] == "executed"
