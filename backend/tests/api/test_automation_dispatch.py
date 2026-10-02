"""Tests for Agent Hub-owned automation dispatch callbacks."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.automation_dispatch import (
    AutomationClockFenceRequest,
    AutomationDispatchRequest,
    BrowserWorkflowControlRequest,
    _policy_is_valid,
    control_browser_workflow,
    dispatch_automation,
    fence_automation_clock,
)

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


def _request(**overrides: object) -> AutomationDispatchRequest:
    values: dict[str, object] = {
        "run_id": "run-1",
        "profile_id": "profile-1",
        "project_id": "agent-hub",
        "workflow_key": "work_pickup",
        "definition_version": 1,
        "profile_revision": 2,
        "occurrence_key": "occurrence-1",
        "trigger": "scheduled",
        "scheduled_for": "2026-09-23T14:00:00Z",
        "config": {"upkeep_batch_limit": 5},
        "policy_config": _POLICY,
    }
    values.update(overrides)
    return AutomationDispatchRequest.model_validate(values)


@pytest.mark.asyncio
async def test_dispatch_rejects_missing_or_wrong_internal_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")

    with pytest.raises(HTTPException) as missing:
        await dispatch_automation("work_pickup", _request(), "")
    with pytest.raises(HTTPException) as wrong:
        await dispatch_automation("work_pickup", _request(), "wrong-secret")

    assert missing.value.status_code == 403
    assert wrong.value.status_code == 403


@pytest.mark.asyncio
async def test_dispatch_fails_closed_when_internal_secret_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)

    with pytest.raises(HTTPException) as exc:
        await dispatch_automation("work_pickup", _request(), "anything")

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_dispatch_rejects_incomplete_central_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")

    with pytest.raises(HTTPException) as exc:
        await dispatch_automation(
            "work_pickup",
            _request(policy_config={"autonomous_max_concurrent": 1}),
            "expected-secret",
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_clock_fence_uses_internal_secret_and_persists_owner(mocker, monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")
    persist = mocker.patch(
        "app.storage.automation_clock_fences.fence_clock_to_agent_hub",
        return_value="d31c0b80-608b-5c0b-8ef5-a020a6a9b83d",
    )

    result = await fence_automation_clock(
        "work_pickup",
        AutomationClockFenceRequest(project_id="agent-hub"),
        "expected-secret",
    )

    assert result.model_dump() == {
        "project_id": "agent-hub",
        "workflow_key": "work_pickup",
        "clock_owner": "agent_hub",
        "status": "fenced",
        "fence_receipt": "d31c0b80-608b-5c0b-8ef5-a020a6a9b83d",
    }
    persist.assert_called_once_with("agent-hub", "work_pickup")


def test_fence_receipt_is_stable_and_scoped_to_project_and_workflow() -> None:
    from app.storage.automation_clock_fences import stable_fence_receipt

    first = stable_fence_receipt("agent-hub", "work_pickup")

    assert first
    assert first == stable_fence_receipt("agent-hub", "work_pickup")
    assert first != stable_fence_receipt("portfolio-ai", "work_pickup")
    assert first != stable_fence_receipt("agent-hub", "task_generation")


def test_policy_validation_allows_ah_generic_filters_field() -> None:
    assert _policy_is_valid({**_POLICY, "filters": {}})


def test_dispatch_request_restores_nulls_omitted_by_agent_hub_serialization() -> None:
    policy = dict(_POLICY)
    del policy["autonomous_max_tasks_per_day"]
    del policy["autonomous_external_origins"]

    request = _request(policy_config=policy)

    assert request.policy_config["autonomous_max_tasks_per_day"] is None
    assert request.policy_config["autonomous_external_origins"] is None


@pytest.mark.asyncio
async def test_work_pickup_accepts_typed_central_batch_limit_and_filters(mocker, monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")
    accept = mocker.patch(
        "app.services.automation_dispatch.accept_automation_dispatch",
        return_value={"owner_run_id": "owner-1", "status": "accepted"},
    )

    result = await dispatch_automation(
        "work_pickup",
        _request(config={"batch_limit": 3}, policy_config={**_POLICY, "filters": {}}),
        "expected-secret",
    )

    assert result.owner_run_id == "owner-1"
    accept.assert_awaited_once()


@pytest.mark.asyncio
async def test_work_pickup_rejects_invalid_central_batch_limit(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")

    with pytest.raises(HTTPException) as exc:
        await dispatch_automation(
            "work_pickup",
            _request(config={"batch_limit": 0}),
            "expected-secret",
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_browser_workflow_accepts_generic_ah_policy_and_immutable_definition(mocker, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")
    accept = mocker.patch(
        "app.services.automation_dispatch.accept_automation_dispatch",
        return_value={"owner_run_id": "owner-browser", "status": "accepted"},
    )
    request = _request(workflow_key="browser_workflow", config={"workflow": {"schema_version": 1, "steps": [{"id": "read"}]}}, policy_config={"daily_limit": 2})
    response = await dispatch_automation("browser_workflow", request, "expected-secret")
    assert response.owner_run_id == "owner-browser"
    accept.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_browser_workflow_rejects_shared_session_before_acceptance(mocker, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")
    accept = mocker.patch("app.services.automation_dispatch.accept_automation_dispatch")
    with pytest.raises(HTTPException) as exc:
        await dispatch_automation("browser_workflow", _request(workflow_key="browser_workflow", config={"workflow": {"schema_version": 1, "steps": [{}]}, "session": "st-local-ai"}, policy_config={}), "expected-secret")
    assert exc.value.status_code == 422
    accept.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_human_resolution_is_authenticated_and_idempotent(mocker, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")
    queue = mocker.patch("app.services.automation_dispatch.control_browser_automation_run", return_value={"owner_run_id": "owner-browser", "status": "accepted"})
    request = BrowserWorkflowControlRequest.model_validate({"action": "resume", "resolution": {"step": "submit", "outcome": "completed"}})
    with pytest.raises(HTTPException) as missing:
        await control_browser_workflow("run-1", request, "control-1", "")
    assert missing.value.status_code == 403
    queue.assert_not_called()
    await control_browser_workflow("run-1", request, "control-1", "expected-secret")
    queue.assert_awaited_once_with("run-1", {"action": "resume", "resolution": {"step": "submit", "outcome": "completed"}, "idempotency_key": "control-1"})


@pytest.mark.asyncio
async def test_control_rejects_active_resume_and_cancel_resolution(mocker, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")
    queue = mocker.patch("app.services.automation_dispatch.control_browser_automation_run", side_effect=ValueError("Browser workflow control requires a waiting human checkpoint"))
    with pytest.raises(HTTPException) as active:
        await control_browser_workflow("run-1", BrowserWorkflowControlRequest(action="resume"), "resume-1", "expected-secret")
    assert active.value.status_code == 409
    queue.reset_mock()
    request = BrowserWorkflowControlRequest.model_validate({"action": "cancel", "resolution": {"step": "submit", "outcome": "retry"}})
    with pytest.raises(HTTPException) as invalid:
        await control_browser_workflow("run-1", request, "cancel-2", "expected-secret")
    assert invalid.value.status_code == 422
    queue.assert_not_called()


@pytest.mark.asyncio
async def test_active_cancel_returns_durable_acceptance_instead_of_conflict(mocker, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")
    queue = mocker.patch("app.services.automation_dispatch.control_browser_automation_run", return_value={"owner_run_id": "owner-browser", "status": "accepted", "receipt": {"cancel_requested": True, "delivery": "pending"}})
    response = await control_browser_workflow("run-1", BrowserWorkflowControlRequest(action="cancel"), "cancel-active", "expected-secret")
    assert response.status == "accepted"
    assert response.receipt["cancel_requested"] is True
    queue.assert_awaited_once_with("run-1", {"action": "cancel", "idempotency_key": "cancel-active"})
