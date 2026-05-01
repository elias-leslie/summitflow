from __future__ import annotations

from collections.abc import Awaitable
from unittest.mock import Mock

import pytest
from hatchet_sdk import ConcurrencyLimitStrategy

from app.workflows.models import EmptyInput
from app.workflows.scheduled import (
    _explorer_schedule_concurrency,
    refresh_graphify_graphs_wf,
    refresh_precision_indexes_wf,
    scan_projects_wf,
)


async def _run_inline(func, *args, **kwargs):
    return func(*args, **kwargs)


def test_explorer_schedule_concurrency_uses_shared_cancel_newest() -> None:
    concurrency = _explorer_schedule_concurrency()

    assert concurrency.expression == "'summitflow-explorer-maintenance'"
    assert concurrency.max_runs == 1
    assert concurrency.limit_strategy == ConcurrencyLimitStrategy.CANCEL_NEWEST


@pytest.mark.asyncio
async def test_scan_projects_wf_uses_isolated_process(monkeypatch) -> None:
    dispatch = Mock()
    scan_all_projects = Mock(return_value={"status": "success"})

    monkeypatch.setattr("app.workflows.scheduled._system_schedule_enabled", lambda _schedule_id: True)
    monkeypatch.setattr("app.workflows.scheduled.asyncio.to_thread", _run_inline)
    monkeypatch.setattr("app.tasks.explorer_tasks.scan_all_projects", scan_all_projects)
    monkeypatch.setattr("app.workflows.pipeline._make_dispatch_callback", lambda: dispatch)

    call = scan_projects_wf._task.fn(EmptyInput(), None)
    assert isinstance(call, Awaitable)
    result = await call

    assert result == {"status": "success"}
    scan_all_projects.assert_called_once_with(
        dry_run=False,
        dispatch=dispatch,
        isolate_process=True,
    )


@pytest.mark.asyncio
async def test_refresh_precision_indexes_wf_uses_isolated_process(monkeypatch) -> None:
    scan_all_projects = Mock(return_value={"status": "success"})

    monkeypatch.setattr("app.workflows.scheduled._system_schedule_enabled", lambda _schedule_id: True)
    monkeypatch.setattr("app.workflows.scheduled.asyncio.to_thread", _run_inline)
    monkeypatch.setattr("app.tasks.explorer_tasks.scan_all_projects", scan_all_projects)

    call = refresh_precision_indexes_wf._task.fn(EmptyInput(), None)
    assert isinstance(call, Awaitable)
    result = await call

    assert result == {"status": "success"}
    scan_all_projects.assert_called_once_with(
        entry_type="file",
        dry_run=False,
        dispatch=None,
        isolate_process=True,
    )


@pytest.mark.asyncio
async def test_refresh_graphify_graphs_wf_uses_shared_maintenance_lane(monkeypatch) -> None:
    refresh_existing_graphify_graphs = Mock(return_value={"status": "success", "refreshed": 1})

    monkeypatch.setattr("app.workflows.scheduled._system_schedule_enabled", lambda _schedule_id: True)
    monkeypatch.setattr("app.workflows.scheduled.asyncio.to_thread", _run_inline)
    monkeypatch.setattr(
        "app.tasks.graphify_tasks.refresh_existing_graphify_graphs",
        refresh_existing_graphify_graphs,
    )

    call = refresh_graphify_graphs_wf._task.fn(EmptyInput(), None)
    assert isinstance(call, Awaitable)
    result = await call

    assert result == {"status": "success", "refreshed": 1}
    refresh_existing_graphify_graphs.assert_called_once_with()
