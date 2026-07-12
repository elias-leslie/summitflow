"""Focused unit coverage for truthful direct task completion responses."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.tasks import TaskStatusUpdate


@pytest.mark.asyncio
async def test_direct_completion_stays_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    """Manual/no-code completion must not manufacture autonomous evidence."""
    from app.api.tasks import crud_handlers, update_endpoints

    task_id = "task-manual"
    project_id = "summitflow"
    completed = {
        "id": task_id,
        "project_id": project_id,
        "status": "completed",
        "verification_result": None,
    }

    monkeypatch.setattr(
        update_endpoints,
        "verify_task_project",
        lambda _task_id, _project_id: {**completed, "status": "running"},
    )
    update_status = MagicMock(return_value=completed)
    update_task = MagicMock()
    monkeypatch.setattr(update_endpoints.task_store, "update_task_status", update_status)
    monkeypatch.setattr(update_endpoints.task_store, "update_task", update_task)
    completion_gate = AsyncMock()
    monkeypatch.setattr(crud_handlers, "validate_completion_gates", completion_gate)
    dispatch = AsyncMock()
    monkeypatch.setattr(update_endpoints, "dispatch_autonomous_task", dispatch)
    monkeypatch.setattr(update_endpoints, "task_to_response", lambda task: task)

    result = await update_endpoints.update_task_status(
        project_id,
        task_id,
        TaskStatusUpdate(status="completed"),
    )
    result_data = cast(dict[str, Any], result)

    assert result_data["status"] == "completed"
    assert result_data["verification_result"] is None
    update_task.assert_not_called()
    completion_gate.assert_awaited_once_with(task_id)
    dispatch.assert_awaited_once_with(task_id, "completed", project_id)
