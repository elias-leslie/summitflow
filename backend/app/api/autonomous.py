"""Autonomous execution settings API."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import AGENT_HUB_URL
from ..services._agent_hub_config import build_agent_hub_headers
from ..services.autonomous_schedule_registry import (
    get_autonomous_schedule_definition,
    list_autonomous_schedule_states,
    set_autonomous_schedule_enabled,
)
from ..storage import maintenance_runs as maintenance_store
from ..tasks.autonomous.upkeep import (
    ROUTINE_UPKEEP_WORKFLOW,
    get_routine_upkeep_settings,
    run_routine_upkeep,
)
from .autonomous_models import AutonomousSettings, AutonomousSettingsUpdate
from .autonomous_service import (
    get_autonomous_settings as _get_settings,
)
from .dependencies import validate_project_exists

router = APIRouter()

# Re-export models for backward compatibility
__all__ = [
    "AutonomousSettings",
    "AutonomousSettingsUpdate",
    "router",
]


class RoutineUpkeepSettingsResponse(BaseModel):
    """Routine upkeep settings exposed in status responses."""

    enabled: bool
    frequency_minutes: int
    batch_limit: int


class RoutineUpkeepRunResponse(BaseModel):
    """Routine upkeep run result."""

    project_id: str
    status: str
    tasks_created: int = 0
    dispatch: dict[str, Any] = Field(default_factory=dict)
    created_task_ids: list[str] = Field(default_factory=list)
    sources: dict[str, Any] = Field(default_factory=dict)
    source_errors: dict[str, str] = Field(default_factory=dict)
    reason: str | None = None


class RoutineUpkeepHistoryRun(BaseModel):
    """Recorded routine upkeep run."""

    id: int
    workflow_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    rows_cleaned: int
    summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime


class RoutineUpkeepStatusResponse(BaseModel):
    """Routine upkeep status and recent history."""

    settings: RoutineUpkeepSettingsResponse
    latest: RoutineUpkeepHistoryRun | None = None
    recent: list[RoutineUpkeepHistoryRun] = Field(default_factory=list)


class AutonomousScheduleResponse(BaseModel):
    """UI-manageable scheduled workflow metadata."""

    schedule_id: str
    config_key: str
    label: str
    description: str
    cron: str
    scope: str
    default_enabled: bool
    enabled: bool
    managed_project_id: str


class AutonomousScheduleUpdate(BaseModel):
    """Enable/disable payload for a single schedule."""

    enabled: bool


async def _fetch_agent_hub_execution_permission(project_id: str) -> dict[str, Any]:
    """Fetch lightweight Agent Hub execution status without failing settings load."""
    url = f"{AGENT_HUB_URL}/api/projects/{project_id}/execution-permission"
    headers = build_agent_hub_headers(request_source="summitflow-autonomous-settings")
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
            response = await client.get(url)
    except Exception as exc:
        return {
            "allowed": False,
            "auto_exec_enabled": False,
            "in_time_window": False,
            "permission_tier": None,
            "reason": f"agent_hub_unreachable: {exc}",
        }
    if response.status_code == 404:
        return {
            "allowed": False,
            "auto_exec_enabled": False,
            "in_time_window": False,
            "permission_tier": None,
            "reason": "permission_missing",
        }
    if response.status_code >= 400:
        return {
            "allowed": False,
            "auto_exec_enabled": False,
            "in_time_window": False,
            "permission_tier": None,
            "reason": f"agent_hub_http_{response.status_code}",
        }
    payload = response.json()
    return payload if isinstance(payload, dict) else {
        "allowed": False,
        "auto_exec_enabled": False,
        "in_time_window": False,
        "permission_tier": None,
        "reason": "invalid_agent_hub_response",
    }


async def _settings_with_execution_permission(project_id: str) -> AutonomousSettings:
    settings = _get_settings(project_id)
    permission = await _fetch_agent_hub_execution_permission(project_id)
    return settings.model_copy(
        update={
            "enabled": bool(permission.get("auto_exec_enabled")),
            "execution_allowed": bool(permission.get("allowed")),
            "execution_in_time_window": bool(permission.get("in_time_window", True)),
            "permission_tier": permission.get("permission_tier"),
            "permission_reason": permission.get("reason"),
        }
    )


@router.get("/{project_id}/autonomous/settings", response_model=AutonomousSettings)
async def get_settings(project_id: str) -> AutonomousSettings:
    """Get autonomous execution settings for a project."""
    validate_project_exists(project_id)
    return await _settings_with_execution_permission(project_id)


@router.patch("/{project_id}/autonomous/settings", response_model=AutonomousSettings)
async def update_settings(project_id: str, update: AutonomousSettingsUpdate) -> AutonomousSettings:
    """Retire the local writer after Agent Hub took ownership of these settings."""
    validate_project_exists(project_id)
    raise HTTPException(
        status_code=410,
        detail="Automation settings are managed in Agent Hub Automations. Use st automations policy and policy-apply, or edit the project's profiles there.",
    )


@router.get("/{project_id}/autonomous/upkeep/status", response_model=RoutineUpkeepStatusResponse)
async def get_upkeep_status(project_id: str) -> RoutineUpkeepStatusResponse:
    """Get routine upkeep settings and recent run history."""
    validate_project_exists(project_id)
    settings = get_routine_upkeep_settings(project_id)
    recent = [
        RoutineUpkeepHistoryRun(**run)
        for run in maintenance_store.list_maintenance_runs(
            limit=5,
            workflow_name=ROUTINE_UPKEEP_WORKFLOW,
            project_id=project_id,
        )
    ]
    return RoutineUpkeepStatusResponse(
        settings=RoutineUpkeepSettingsResponse(
            enabled=settings.enabled,
            frequency_minutes=settings.frequency_minutes,
            batch_limit=settings.batch_limit,
        ),
        latest=recent[0] if recent else None,
        recent=recent,
    )


@router.get("/{project_id}/autonomous/schedules", response_model=list[AutonomousScheduleResponse])
async def get_autonomous_schedules(project_id: str) -> list[AutonomousScheduleResponse]:
    """List every SummitFlow schedule with its current enablement source."""
    validate_project_exists(project_id)
    return [AutonomousScheduleResponse(**item) for item in list_autonomous_schedule_states(project_id)]


@router.patch(
    "/{project_id}/autonomous/schedules/{schedule_id}",
    response_model=AutonomousScheduleResponse,
)
async def update_autonomous_schedule(
    project_id: str,
    schedule_id: str,
    update: AutonomousScheduleUpdate,
) -> AutonomousScheduleResponse:
    """Keep local controls only for schedules not owned by Agent Hub."""
    validate_project_exists(project_id)
    try:
        definition = get_autonomous_schedule_definition(schedule_id)
        if definition.schedule_id in {"work_pickup", "task_generation"}:
            raise HTTPException(
                status_code=410,
                detail="This schedule is managed in Agent Hub Automations. Use st automations list and enable/disable for its profile.",
            )
        payload = set_autonomous_schedule_enabled(project_id, schedule_id, enabled=update.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown autonomous schedule '{schedule_id}'") from exc
    return AutonomousScheduleResponse(**payload)


@router.post("/{project_id}/autonomous/upkeep/run", response_model=RoutineUpkeepRunResponse)
async def run_upkeep(project_id: str) -> RoutineUpkeepRunResponse:
    """Run one routine upkeep discovery cycle immediately."""
    validate_project_exists(project_id)
    result = await asyncio.to_thread(
        run_routine_upkeep,
        project_id,
        force=True,
    )
    return RoutineUpkeepRunResponse(**result)
