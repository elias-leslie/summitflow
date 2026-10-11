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
    mocker.patch("app.services.automation_dispatch.automation_dispatches.list_browser_cancellation_requests", return_value=[])
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
@pytest.mark.parametrize("workflow_key", ["work_pickup", "task_generation"])
async def test_retired_autonomous_workflows_are_skipped_without_domain_work(mocker, workflow_key) -> None:
    payload = {
        "workflow_key": workflow_key,
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
        "workflow_key": workflow_key,
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
    browser = mocker.patch("app.services.automation_dispatch.execute_browser_workflow", new_callable=AsyncMock)

    result = await automation_dispatch.execute_automation_run(
        "run-1", "owner-1", worker_run_id="hatchet-1"
    )

    assert result["status"] == "skipped"
    assert finish.call_args.kwargs["status"] == "skipped"
    assert finish.call_args.kwargs["result"]["reason"] == "workflow_retired"
    domain.assert_not_called()
    browser.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_and_browser_wait_report_through_sdk(mocker, monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "shared-secret")
    client = AsyncMock()
    client.__aenter__.return_value = client
    mocker.patch.object(automation_dispatch, "get_async_client", return_value=client)
    mark = mocker.patch.object(
        automation_dispatch.automation_dispatches, "mark_automation_completion_reported"
    )
    receipt = {
        "run_id": "run-1", "owner_run_id": "owner-1", "status": "failed",
        "error": "boom", "result": {"step": 2},
    }

    await automation_dispatch._report_completion(receipt)
    await automation_dispatch._report_browser_wait(receipt)

    client.complete_automation_run.assert_awaited_once_with(
        "run-1",
        {"status": "failed", "owner_run_id": "owner-1", "error": "boom", "receipt": {"step": 2}},
        internal_secret="shared-secret",
    )
    client.accept_automation_run.assert_awaited_once_with(
        "run-1", {"owner_run_id": "owner-1", "receipt": {"step": 2}}, internal_secret="shared-secret"
    )
    mark.assert_called_once_with("run-1")
