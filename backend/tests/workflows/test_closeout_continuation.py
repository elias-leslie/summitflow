"""Existing maintenance continues authorized closeouts, independent of claim reset."""
from collections.abc import Awaitable
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from app.workflows.models import EmptyInput, TaskInput
from app.workflows.scheduled import reset_claims_wf
from app.workflows.utility import checkpoint_cleanup_wf


@pytest.mark.asyncio
async def test_closeout_dispatch_survives_disabled_claim_reset(monkeypatch):
    monkeypatch.setattr('app.workflows.scheduled._system_schedule_enabled', lambda _: False)
    monkeypatch.setattr('app.services.task_closeout.pending_closeouts',
                        lambda: [{'task_id': 'task-one', 'project_id': 'project-one'}])
    dispatch = AsyncMock()
    monkeypatch.setattr(checkpoint_cleanup_wf, 'aio_run_no_wait', dispatch)
    reset = Mock(side_effect=AssertionError('claim reset is disabled'))
    monkeypatch.setattr('app.tasks.autonomous.cleanup.reset_expired_task_claims', reset)
    call = reset_claims_wf._task.fn(EmptyInput(), None)
    assert isinstance(call, Awaitable)
    result = await call
    assert isinstance(result, dict)
    assert cast(dict[str, Any], result)['closeouts_dispatched'] == 1
    dispatch.assert_awaited_once_with(TaskInput(task_id='task-one', project_id='project-one'))
    reset.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_worker_keeps_project_identity(monkeypatch):
    monkeypatch.setattr('app.services.task_closeout.get_closeout', lambda _: None)
    cleanup = Mock(return_value={'status': 'cleaned'})
    monkeypatch.setattr('app.tasks.autonomous.cleanup.cleanup_task_checkpoint', cleanup)
    call = checkpoint_cleanup_wf._task.fn(TaskInput(task_id='task-one', project_id='project-one'), None)
    assert isinstance(call, Awaitable)
    assert await call == {'status': 'cleaned'}
    cleanup.assert_called_once_with('task-one', project_id='project-one')
