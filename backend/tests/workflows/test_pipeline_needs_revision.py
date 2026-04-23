from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, cast

import pytest

from app.workflows.models import TaskInput
from app.workflows.pipeline import critique_wf


async def _run_inline(func, *args, **kwargs):
    return func(*args, **kwargs)


@pytest.mark.asyncio
async def test_critique_wf_does_not_auto_replan_needs_revision(monkeypatch) -> None:
    triggered: list[tuple[str, str, str]] = []

    monkeypatch.setattr("app.workflows.pipeline.asyncio.to_thread", _run_inline)
    monkeypatch.setattr(
        "app.tasks.autonomous.critique.run_task_shape_critique",
        lambda task_id, project_id: {
            "task_id": task_id,
            "status": "completed",
            "verdict": "NEEDS_REVISION",
            "summary": "Needs tighter package.",
        },
    )

    async def fake_trigger(stage: str, task_id: str, project_id: str) -> None:
        triggered.append((stage, task_id, project_id))

    monkeypatch.setattr("app.workflows.pipeline._trigger_workflow", fake_trigger)

    call = critique_wf._task.fn(TaskInput(task_id="task-123", project_id="summitflow"), None)
    assert isinstance(call, Awaitable)
    result = cast(dict[str, Any], await call)

    assert result["verdict"] == "NEEDS_REVISION"
    assert triggered == []
