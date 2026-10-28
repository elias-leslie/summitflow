"""Internal callbacks for Agent Hub-owned SummitFlow automation runs."""

from __future__ import annotations

import hmac
import os
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()

WorkflowKey = Literal["browser_workflow"]


class AutomationDispatchRequest(BaseModel):
    """Versioned Agent Hub run envelope accepted by the owner callback."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=200)
    profile_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    workflow_key: WorkflowKey
    definition_version: int = Field(ge=1)
    profile_revision: int = Field(ge=1)
    occurrence_key: str = Field(min_length=1, max_length=300)
    trigger: Literal["scheduled", "manual", "retry"]
    scheduled_for: datetime
    config: dict[str, Any]
    policy_config: dict[str, Any]


class AutomationDispatchResponse(BaseModel):
    owner_run_id: str
    status: str
    receipt: dict[str, Any] = Field(default_factory=dict)


def _verify_internal_secret(secret: str) -> None:
    expected = os.environ.get("INTERNAL_SERVICE_SECRET", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal automation callback authentication is unavailable",
        )
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


async def dispatch_automation(
    workflow_key: str,
    request: AutomationDispatchRequest,
    internal_secret: str,
) -> AutomationDispatchResponse:
    """Authenticate and hand an Agent Hub run to the durable owner outbox."""
    _verify_internal_secret(internal_secret)
    if workflow_key != "browser_workflow":
        raise HTTPException(status_code=404, detail="Unknown automation workflow")
    if request.workflow_key != workflow_key:
        raise HTTPException(status_code=409, detail="Workflow key does not match route")
    from ..services.automation_dispatch import (
        accept_automation_dispatch,
        validate_browser_workflow_config,
    )

    try:
        validate_browser_workflow_config(request.config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        receipt = await accept_automation_dispatch(request)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to accept automation run") from exc
    return AutomationDispatchResponse(**receipt)


@router.post(
    "/automations/dispatch/{workflow_key}",
    response_model=AutomationDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def dispatch_automation_callback(
    workflow_key: WorkflowKey,
    request: AutomationDispatchRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    internal_secret: str = Header(default="", alias="X-Agent-Hub-Internal"),
) -> AutomationDispatchResponse:
    if idempotency_key != request.run_id:
        raise HTTPException(status_code=409, detail="Idempotency key must match run_id")
    return await dispatch_automation(workflow_key, request, internal_secret)


class BrowserWorkflowResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: str = Field(min_length=1, max_length=200)
    outcome: Literal["completed", "retry"]


class BrowserWorkflowControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["resume", "cancel"]
    resolution: BrowserWorkflowResolution | None = None


@router.post("/automations/runs/{run_id}/control", response_model=AutomationDispatchResponse)
async def control_browser_workflow(
    run_id: str,
    request: BrowserWorkflowControlRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    internal_secret: str = Header(default="", alias="X-Agent-Hub-Internal"),
) -> AutomationDispatchResponse:
    """Explicitly reconcile a human checkpoint through the same durable outbox."""
    _verify_internal_secret(internal_secret)
    if request.action == "cancel" and request.resolution is not None:
        raise HTTPException(status_code=422, detail="Cancel does not accept a step resolution")
    from ..services.automation_dispatch import control_browser_automation_run

    try:
        receipt = await control_browser_automation_run(run_id, {**request.model_dump(exclude_none=True), "idempotency_key": idempotency_key})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Browser automation run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to queue browser workflow control") from exc
    return AutomationDispatchResponse(**receipt)
