from __future__ import annotations

from collections.abc import Awaitable
from unittest.mock import Mock

import pytest
from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy

from app.workflows.models import EmptyInput
from app.workflows.scheduled import (
    _project_maintenance_concurrency,
    hatchet_retention_wf,
    refresh_graphify_graphs_wf,
    refresh_project_indexes_wf,
    scheduled_backups_wf,
)


async def _run_inline(func, *args, **kwargs):
    return func(*args, **kwargs)


def test_project_maintenance_concurrency_uses_shared_cancel_newest() -> None:
    concurrency = _project_maintenance_concurrency()

    assert concurrency.expression == "'summitflow-project-maintenance'"
    assert concurrency.max_runs == 1
    assert concurrency.limit_strategy == ConcurrencyLimitStrategy.CANCEL_NEWEST


def test_hatchet_retention_schedule_is_registry_managed() -> None:
    from app.services.schedule_registry import get_schedule_definition

    definition = get_schedule_definition("hatchet_retention")

    assert definition.config_key == "hatchet_retention_enabled"
    assert definition.cron == "45 4 * * 0"
    assert definition.scope == "system"
    assert definition.default_enabled is True


def test_scheduled_backups_is_a_short_health_check() -> None:
    """The hourly task only checks backup health; the backup itself runs from the systemd timer."""
    assert scheduled_backups_wf._task.execution_timeout == "900s"


def test_scheduled_backups_skip_overlapping_cron_instead_of_killing_active_sweep() -> None:
    concurrency = scheduled_backups_wf._task.concurrency
    assert concurrency is not None
    constraints = concurrency if isinstance(concurrency, list) else [concurrency]
    assert len(constraints) == 1
    constraint = constraints[0]
    assert isinstance(constraint, ConcurrencyExpression)
    assert constraint.limit_strategy == ConcurrencyLimitStrategy.CANCEL_NEWEST


@pytest.mark.asyncio
async def test_refresh_project_indexes_wf_writes_every_index(monkeypatch) -> None:
    write_all_index_files = Mock(return_value={"alpha": "/a/.index.yaml", "beta": None, "gamma": "/g/.index.yaml"})

    monkeypatch.setattr("app.workflows.scheduled._system_schedule_enabled", lambda _schedule_id: True)
    monkeypatch.setattr("app.workflows.scheduled.asyncio.to_thread", _run_inline)
    monkeypatch.setattr("app.services.project_index.write_all_index_files", write_all_index_files)

    call = refresh_project_indexes_wf._task.fn(EmptyInput(), None)
    assert isinstance(call, Awaitable)
    result = await call

    assert result == {"status": "partial", "written": 2, "failed": ["beta"]}
    write_all_index_files.assert_called_once_with()


@pytest.mark.asyncio
async def test_refresh_project_indexes_wf_respects_disabled_flag(monkeypatch) -> None:
    write_all_index_files = Mock()

    monkeypatch.setattr("app.workflows.scheduled._system_schedule_enabled", lambda _schedule_id: False)
    monkeypatch.setattr("app.services.project_index.write_all_index_files", write_all_index_files)

    result = await refresh_project_indexes_wf._task.fn(EmptyInput(), None)

    assert result == {"schedule_id": "refresh_project_indexes", "status": "disabled"}
    write_all_index_files.assert_not_called()


def test_project_index_refresh_shares_the_maintenance_lane() -> None:
    from app.services.schedule_registry import get_schedule_definition

    definition = get_schedule_definition("refresh_project_indexes")
    assert definition.config_key == "refresh_project_indexes_enabled"
    assert definition.scope == "system"
    for workflow in (refresh_project_indexes_wf, refresh_graphify_graphs_wf):
        concurrency = workflow._task.concurrency
        constraints = concurrency if isinstance(concurrency, list) else [concurrency]
        assert len(constraints) == 1
        constraint = constraints[0]
        assert isinstance(constraint, ConcurrencyExpression)
        assert constraint.expression == "'summitflow-project-maintenance'"


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


def test_tool_governance_has_no_schedule_or_worker_route() -> None:
    from app.services.schedule_registry import list_schedule_definitions
    from app.worker import _registered_workflows

    assert "tool_governance" not in {item.schedule_id for item in list_schedule_definitions()}
    assert "summitflow-tool-governance" not in {
        workflow._task.name for workflow in _registered_workflows()
    }


@pytest.mark.asyncio
async def test_hatchet_retention_wf_runs_retention_guard(monkeypatch) -> None:
    run_hatchet_retention_guard = Mock(return_value={"status": "success", "total_deleted": 4})

    monkeypatch.setattr("app.workflows.scheduled._system_schedule_enabled", lambda _schedule_id: True)
    monkeypatch.setattr("app.workflows.scheduled.asyncio.to_thread", _run_inline)
    monkeypatch.setattr(
        "app.tasks.hatchet_retention.run_hatchet_retention_guard",
        run_hatchet_retention_guard,
    )

    call = hatchet_retention_wf._task.fn(EmptyInput(), None)
    assert isinstance(call, Awaitable)
    result = await call

    assert result == {"status": "success", "total_deleted": 4}
    run_hatchet_retention_guard.assert_called_once_with()


def _crons(workflow: object) -> list[str]:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return list(workflow.config.on_crons)  # type: ignore[attr-defined]


def test_project_index_and_graph_refresh_keep_cadence() -> None:
    assert _crons(refresh_project_indexes_wf) == ["0 */6 * * *"]
    assert _crons(refresh_graphify_graphs_wf) == ["25 */2 * * *"]
