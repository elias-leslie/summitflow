"""Queued maintenance cannot resume retired remote closeouts."""
from collections.abc import Awaitable
from unittest.mock import AsyncMock, Mock

import pytest

from app.workflows.models import EmptyInput, TaskInput
from app.workflows.scheduled import reset_claims_wf
from app.workflows.utility import checkpoint_cleanup_wf


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_claim_maintenance_never_dispatches_remote_closeout(monkeypatch, enabled):
    monkeypatch.setattr("app.workflows.scheduled._system_schedule_enabled", lambda _: enabled)
    dispatch = AsyncMock(side_effect=AssertionError("No remote continuation"))
    monkeypatch.setattr(checkpoint_cleanup_wf, "aio_run_no_wait", dispatch)
    reset = Mock(return_value={"status": "success"})
    monkeypatch.setattr("app.tasks.autonomous.cleanup.reset_expired_task_claims", reset)
    call = reset_claims_wf._task.fn(EmptyInput(), None)
    assert isinstance(call, Awaitable)
    await call
    dispatch.assert_not_called()
    assert reset.call_count == int(enabled)


@pytest.mark.asyncio
async def test_queued_cleanup_never_resumes_publication(monkeypatch):
    remote = Mock(side_effect=AssertionError("No remote publication"))
    monkeypatch.setattr("app.services.task_closeout.resume_closeout", remote)
    cleanup = Mock(return_value={"status": "cleaned"})
    monkeypatch.setattr("app.tasks.autonomous.cleanup.cleanup_task_checkpoint", cleanup)
    call = checkpoint_cleanup_wf._task.fn(TaskInput(task_id="task-one", project_id="project-one"), None)
    assert isinstance(call, Awaitable)
    assert await call == {"status": "cleaned"}
    cleanup.assert_called_once_with("task-one", project_id="project-one")
    remote.assert_not_called()
