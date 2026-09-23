"""Tests for durable acceptance of Agent Hub automation runs."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.api.automation_dispatch import AutomationDispatchRequest
from app.services import automation_dispatch

_POLICY = {
    "autonomous_enabled": True,
    "routine_upkeep_enabled": True,
    "autonomous_max_concurrent": 2,
    "autonomous_max_tasks_per_day": None,
    "autonomous_cooldown_minutes": 0,
    "autonomous_allowed_types": ["task"],
    "autonomous_external_origins": None,
    "autonomous_start_hour": 0,
    "autonomous_end_hour": 24,
    "autonomous_auto_merge_tiers": [1],
    "autonomous_max_self_fix_attempts": 3,
    "autonomous_max_supervisor_attempts": 3,
    "autonomous_max_extensions": 3,
    "autonomous_require_review": False,
    "quality_gate_tools": [],
    "quality_gate_mode": "quick",
    "quality_gate_fix_enabled": True,
}


def test_work_pickup_batch_limit_uses_agent_hub_config_and_legacy_default() -> None:
    assert automation_dispatch._work_pickup_batch_limit({"batch_limit": 3}) == 3
    assert automation_dispatch._work_pickup_batch_limit({}) == 10


def test_work_pickup_batch_limit_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        automation_dispatch._work_pickup_batch_limit({"batch_limit": 0})


def _request() -> AutomationDispatchRequest:
    return AutomationDispatchRequest(
        run_id="run-1",
        profile_id="profile-1",
        project_id="agent-hub",
        workflow_key="work_pickup",
        definition_version=1,
        profile_revision=2,
        occurrence_key="occurrence-1",
        trigger="scheduled",
        scheduled_for=datetime(2026, 9, 23, 14, tzinfo=UTC),
        config={},
        policy_config=_POLICY,
    )


@pytest.mark.asyncio
async def test_accept_persists_before_enqueue_and_returns_stable_owner_id(mocker) -> None:
    events: list[str] = []
    receipt = {
        "run_id": "run-1",
        "owner_run_id": "owner-1",
        "status": "pending",
        "payload": _request().model_dump(mode="json"),
    }
    create = mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.create_or_get_automation_run",
        side_effect=lambda *_args: (events.append("persist") or receipt),
    )
    enqueue = mocker.patch(
        "app.services.automation_dispatch.enqueue_automation_run",
        side_effect=lambda *_args: events.append("enqueue"),
    )
    mark_queued = mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.mark_automation_run_queued",
        side_effect=lambda *_args: (events.append("queued") or {**receipt, "status": "queued"}),
    )

    result = await automation_dispatch.accept_automation_dispatch(_request())

    assert events == ["persist", "enqueue", "queued"]
    assert result == {"owner_run_id": "owner-1", "status": "accepted"}
    create.assert_called_once()
    enqueue.assert_awaited_once()
    mark_queued.assert_called_once_with("run-1")


@pytest.mark.asyncio
async def test_enqueue_failure_leaves_durable_pending_receipt_for_retry(mocker) -> None:
    receipt = {
        "run_id": "run-1",
        "owner_run_id": "owner-1",
        "status": "pending",
        "payload": _request().model_dump(mode="json"),
    }
    create = mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.create_or_get_automation_run",
        return_value=receipt,
    )
    enqueue = mocker.patch(
        "app.services.automation_dispatch.enqueue_automation_run",
        side_effect=[RuntimeError("Hatchet unavailable"), None],
    )
    mark_queued = mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.mark_automation_run_queued",
        return_value={**receipt, "status": "queued"},
    )

    with pytest.raises(RuntimeError):
        await automation_dispatch.accept_automation_dispatch(_request())

    assert await automation_dispatch.accept_automation_dispatch(_request()) == {
        "owner_run_id": "owner-1",
        "status": "accepted",
    }
    assert create.call_count == 2
    assert enqueue.await_count == 2
    mark_queued.assert_called_once_with("run-1")


@pytest.mark.asyncio
async def test_terminal_receipt_retries_completion_report_without_reexecuting(mocker) -> None:
    receipt = {
        "run_id": "run-1",
        "owner_run_id": "owner-1",
        "status": "succeeded",
        "completion_reported_at": None,
        "request_payload": {},
    }
    mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.get_automation_run",
        return_value=receipt,
    )
    report = mocker.patch(
        "app.services.automation_dispatch._report_completion",
        new_callable=AsyncMock,
    )
    claim = mocker.patch("app.services.automation_dispatch.automation_dispatches.claim_automation_run")

    result = await automation_dispatch.execute_automation_run(
        "run-1", "owner-1", worker_run_id="hatchet-run-1"
    )

    assert result == {"run_id": "run-1", "status": "succeeded", "resumed_completion": True}
    report.assert_awaited_once_with(receipt)
    claim.assert_not_called()


@pytest.mark.asyncio
async def test_outbox_reconciler_resumes_pending_receipts(mocker) -> None:
    receipts = [
        {"run_id": "run-1", "owner_run_id": "owner-1"},
        {"run_id": "run-2", "owner_run_id": "owner-2"},
    ]
    mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.list_pending_automation_runs",
        return_value=receipts,
    )
    enqueue = mocker.patch(
        "app.services.automation_dispatch.enqueue_automation_run",
        side_effect=[None, RuntimeError("Hatchet unavailable")],
    )
    mark_queued = mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.mark_automation_run_queued"
    )
    defer = mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.defer_pending_automation_run"
    )

    result = await automation_dispatch.reconcile_pending_automation_runs()

    assert result == {
        "pending": 2,
        "enqueued": 1,
        "failures": ["run-2: RuntimeError"],
    }
    assert enqueue.await_count == 2
    mark_queued.assert_called_once_with("run-1")
    defer.assert_called_once_with("run-2")


@pytest.mark.asyncio
async def test_owner_work_uses_central_work_pickup_batch_limit(mocker) -> None:
    payload = {
        "workflow_key": "work_pickup",
        "profile_id": "profile-1",
        "project_id": "agent-hub",
        "config": {"batch_limit": 3},
        "policy_config": _POLICY,
    }
    receipt = {
        "run_id": "run-1",
        "owner_run_id": "owner-1",
        "status": "queued",
        "request_payload": payload,
        "workflow_key": "work_pickup",
        "profile_id": "profile-1",
        "project_id": "agent-hub",
    }
    mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.get_automation_run",
        return_value=receipt,
    )
    mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.claim_automation_run",
        return_value=receipt,
    )
    mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.finish_automation_run",
        return_value={**receipt, "status": "succeeded", "result": {"dispatched": 0}},
    )
    mocker.patch("app.services.automation_dispatch._report_completion", new_callable=AsyncMock)
    mocker.patch("app.workflows.pipeline._make_dispatch_callback", return_value=object())
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    async def fake_to_thread(function, *args, **kwargs):
        calls.append((function.__name__, args, kwargs))
        return {"status": "completed", "dispatched": 0}

    mocker.patch("app.services.automation_dispatch.asyncio.to_thread", side_effect=fake_to_thread)

    await automation_dispatch.execute_automation_run("run-1", "owner-1", worker_run_id="hatchet-1")

    assert calls[0][2]["limit"] == 3


@pytest.mark.asyncio
async def test_owner_work_respects_central_autonomous_enabled_gate(mocker) -> None:
    payload = {
        "workflow_key": "work_pickup",
        "profile_id": "profile-1",
        "project_id": "agent-hub",
        "config": {"batch_limit": 3},
        "policy_config": {**_POLICY, "autonomous_enabled": False},
    }
    receipt = {
        "run_id": "run-1",
        "owner_run_id": "owner-1",
        "status": "queued",
        "request_payload": payload,
        "workflow_key": "work_pickup",
        "profile_id": "profile-1",
        "project_id": "agent-hub",
    }
    mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.get_automation_run",
        return_value=receipt,
    )
    mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.claim_automation_run",
        return_value=receipt,
    )
    finish = mocker.patch(
        "app.services.automation_dispatch.automation_dispatches.finish_automation_run",
        return_value={**receipt, "status": "skipped"},
    )
    mocker.patch("app.services.automation_dispatch._report_completion", new_callable=AsyncMock)
    domain = mocker.patch("app.services.automation_dispatch.asyncio.to_thread")

    result = await automation_dispatch.execute_automation_run(
        "run-1", "owner-1", worker_run_id="hatchet-1"
    )

    assert result["status"] == "skipped"
    assert finish.call_args.kwargs["status"] == "skipped"
    assert finish.call_args.kwargs["result"]["reason"] == "autonomous_enabled_disabled"
    domain.assert_not_called()
