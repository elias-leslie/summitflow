"""Autonomous execution settings API."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Literal

from agent_hub.exceptions import AgentHubError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services._agent_hub_config import get_async_client
from ..services.autonomous_schedule_registry import (
    AGENT_HUB_OWNED_SCHEDULES,
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
    """Local fallback settings and their provenance, not the Agent Hub policy."""

    source: Literal["legacy_local_inspection"] = "legacy_local_inspection"
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


def _permission_unavailable(reason: str) -> dict[str, Any]:
    return {
        "allowed": False,
        "auto_exec_enabled": False,
        "in_time_window": False,
        "permission_tier": None,
        "reason": reason,
    }


async def _fetch_agent_hub_execution_permission(project_id: str) -> dict[str, Any]:
    """Fetch lightweight Agent Hub execution status without failing settings load."""
    try:
        async with get_async_client(timeout=5.0, request_source="summitflow-autonomous-settings") as client:
            return await client.get_execution_permission(project_id)
    except AgentHubError as exc:
        if exc.status_code == 404:
            return _permission_unavailable("permission_missing")
        if exc.status_code is not None:
            return _permission_unavailable(f"agent_hub_http_{exc.status_code}")
        return _permission_unavailable("invalid_agent_hub_response")
    except Exception as exc:
        return _permission_unavailable(f"agent_hub_unreachable: {exc}")


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
    """Inspect local compatibility settings and live Agent Hub execution permission.

    Agent Hub Automations owns current schedule and policy configuration.
    """
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
    """Get local fallback settings and recent SummitFlow upkeep run history."""
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
    """List locally owned schedules; Agent Hub Automations owns project workflows."""
    validate_project_exists(project_id)
    return [
        AutonomousScheduleResponse(**item)
        for item in list_autonomous_schedule_states(project_id)
        if item["schedule_id"] not in AGENT_HUB_OWNED_SCHEDULES
    ]


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
        if definition.schedule_id in AGENT_HUB_OWNED_SCHEDULES:
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
