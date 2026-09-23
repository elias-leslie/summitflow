"""Internal callbacks for Agent Hub-owned SummitFlow automation runs."""

from __future__ import annotations

import hmac
import os
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

router = APIRouter()

WorkflowKey = Literal["work_pickup", "task_generation"]

_REQUIRED_POLICY_KEYS = {
    "autonomous_enabled",
    "routine_upkeep_enabled",
    "autonomous_max_concurrent",
    "autonomous_max_tasks_per_day",
    "autonomous_cooldown_minutes",
    "autonomous_allowed_types",
    "autonomous_external_origins",
    "autonomous_start_hour",
    "autonomous_end_hour",
    "autonomous_auto_merge_tiers",
    "autonomous_max_self_fix_attempts",
    "autonomous_max_supervisor_attempts",
    "autonomous_max_extensions",
    "autonomous_require_review",
    "quality_gate_tools",
    "quality_gate_mode",
    "quality_gate_fix_enabled",
}


def _policy_is_valid(policy: dict[str, Any]) -> bool:
    if _REQUIRED_POLICY_KEYS.difference(policy):
        return False
    integer_keys = {
        "autonomous_max_concurrent",
        "autonomous_cooldown_minutes",
        "autonomous_start_hour",
        "autonomous_end_hour",
        "autonomous_max_self_fix_attempts",
        "autonomous_max_supervisor_attempts",
        "autonomous_max_extensions",
    }
    if any(type(policy[key]) is not int for key in integer_keys):
        return False
    if policy["autonomous_max_tasks_per_day"] is not None and type(policy["autonomous_max_tasks_per_day"]) is not int:
        return False
    bool_keys = {
        "autonomous_enabled",
        "routine_upkeep_enabled",
        "autonomous_require_review",
        "quality_gate_fix_enabled",
    }
    if any(type(policy[key]) is not bool for key in bool_keys):
        return False
    for key in ("autonomous_allowed_types", "autonomous_auto_merge_tiers", "quality_gate_tools"):
        if not isinstance(policy[key], list):
            return False
    origins = policy["autonomous_external_origins"]
    return origins is None or isinstance(origins, list)


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

    @field_validator("policy_config", mode="before")
    @classmethod
    def normalize_nullable_policy_keys(cls, value: Any) -> Any:
        """Restore explicit nulls omitted by Agent Hub's exclude_none dump."""
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        normalized.setdefault("autonomous_max_tasks_per_day", None)
        normalized.setdefault("autonomous_external_origins", None)
        return normalized


class AutomationDispatchResponse(BaseModel):
    owner_run_id: str
    status: str


class AutomationClockFenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=200)


class AutomationClockFenceResponse(BaseModel):
    project_id: str
    workflow_key: WorkflowKey
    clock_owner: Literal["agent_hub"]
    status: Literal["fenced"]
    fence_receipt: str = Field(min_length=1)


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
    if workflow_key not in {"work_pickup", "task_generation"}:
        raise HTTPException(status_code=404, detail="Unknown automation workflow")
    if request.workflow_key != workflow_key:
        raise HTTPException(status_code=409, detail="Workflow key does not match route")
    if not _policy_is_valid(request.policy_config):
        raise HTTPException(status_code=422, detail="Agent Hub policy snapshot is incomplete")
    if request.workflow_key == "work_pickup":
        batch_limit = request.config.get("batch_limit")
        if batch_limit is not None and (type(batch_limit) is not int or batch_limit < 1):
            raise HTTPException(status_code=422, detail="Agent Hub work-pickup batch_limit must be a positive integer")
    if request.workflow_key == "task_generation" and type(request.config.get("upkeep_batch_limit")) is not int:
        raise HTTPException(status_code=422, detail="Agent Hub task-generation config is incomplete")

    from ..services.automation_dispatch import accept_automation_dispatch

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


@router.post(
    "/automations/clock-fences/{workflow_key}",
    response_model=AutomationClockFenceResponse,
)
async def fence_automation_clock(
    workflow_key: WorkflowKey,
    request: AutomationClockFenceRequest,
    internal_secret: str = Header(default="", alias="X-Agent-Hub-Internal"),
) -> AutomationClockFenceResponse:
    """Drain an admitted local tick before AH changes the central clock owner."""
    _verify_internal_secret(internal_secret)
    from ..storage.automation_clock_fences import fence_clock_to_agent_hub

    try:
        fence_receipt = fence_clock_to_agent_hub(request.project_id, workflow_key)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to fence local automation clock") from exc
    return AutomationClockFenceResponse(
        project_id=request.project_id,
        workflow_key=workflow_key,
        clock_owner="agent_hub",
        status="fenced",
        fence_receipt=fence_receipt,
    )
