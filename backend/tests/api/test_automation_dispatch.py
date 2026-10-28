"""Tests for Agent Hub-owned automation dispatch callbacks."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.automation_dispatch import (
    AutomationDispatchRequest,
    BrowserWorkflowControlRequest,
    control_browser_workflow,
    dispatch_automation,
)

_WORKFLOW_CONFIG = {"workflow": {"schema_version": 1, "steps": [{"id": "read"}]}}


def _request(**overrides: object) -> AutomationDispatchRequest:
    values: dict[str, object] = {
        "run_id": "run-1",
        "profile_id": "profile-1",
        "project_id": "agent-hub",
        "workflow_key": "browser_workflow",
        "definition_version": 1,
        "profile_revision": 2,
        "occurrence_key": "occurrence-1",
        "trigger": "scheduled",
        "scheduled_for": "2026-09-23T14:00:00Z",
        "config": _WORKFLOW_CONFIG,
        "policy_config": {},
    }
    values.update(overrides)
    return AutomationDispatchRequest.model_validate(values)


@pytest.mark.asyncio
async def test_dispatch_rejects_missing_or_wrong_internal_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")

    with pytest.raises(HTTPException) as missing:
        await dispatch_automation("browser_workflow", _request(), "")
    with pytest.raises(HTTPException) as wrong:
        await dispatch_automation("browser_workflow", _request(), "wrong-secret")

    assert missing.value.status_code == 403
    assert wrong.value.status_code == 403


@pytest.mark.asyncio
async def test_dispatch_fails_closed_when_internal_secret_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)

    with pytest.raises(HTTPException) as exc:
        await dispatch_automation("browser_workflow", _request(), "anything")

    assert exc.value.status_code == 503


def test_dispatch_rejects_retired_autonomous_workflow_keys() -> None:
    for workflow_key in ("work_pickup", "task_generation"):
        with pytest.raises(ValidationError):
            _request(workflow_key=workflow_key)


@pytest.mark.asyncio
async def test_dispatch_rejects_unknown_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")

    with pytest.raises(HTTPException) as unknown:
        await dispatch_automation("work_pickup", _request(), "expected-secret")

    assert unknown.value.status_code == 404


@pytest.mark.asyncio
async def test_browser_workflow_accepts_generic_ah_policy_and_immutable_definition(mocker, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")
    accept = mocker.patch(
        "app.services.automation_dispatch.accept_automation_dispatch",
        return_value={"owner_run_id": "owner-browser", "status": "accepted"},
    )
    request = _request(policy_config={"daily_limit": 2})
    response = await dispatch_automation("browser_workflow", request, "expected-secret")
    assert response.owner_run_id == "owner-browser"
    accept.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_browser_workflow_rejects_shared_session_before_acceptance(mocker, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "expected-secret")
    accept = mocker.patch("app.services.automation_dispatch.accept_automation_dispatch")
    with pytest.raises(HTTPException) as exc:
        await dispatch_automation("browser_workflow", _request(config={"workflow": {"schema_version": 1, "steps": [{}]}, "session": "st-local-ai"}), "expected-secret")
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
