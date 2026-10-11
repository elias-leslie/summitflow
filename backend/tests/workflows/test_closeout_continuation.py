"""Claim maintenance only resets expired claims and never resumes remote closeouts."""
from collections.abc import Awaitable
from unittest.mock import Mock

import pytest

from app.workflows.models import EmptyInput
from app.workflows.scheduled import reset_claims_wf


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_claim_maintenance_never_dispatches_remote_closeout(monkeypatch, enabled):
    monkeypatch.setattr("app.workflows.scheduled._system_schedule_enabled", lambda _: enabled)
    remote = Mock(side_effect=AssertionError("No remote publication"))
    monkeypatch.setattr("app.services.task_closeout.resume_closeout", remote)
    reset = Mock(return_value={"status": "success"})
    monkeypatch.setattr("app.tasks.task_claims.reset_expired_task_claims", reset)
    call = reset_claims_wf._task.fn(EmptyInput(), None)
    assert isinstance(call, Awaitable)
    await call
    remote.assert_not_called()
    assert reset.call_count == int(enabled)
