"""Autonomous execution settings API."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.autonomous_schedule_registry import (
    list_autonomous_schedule_states,
    set_autonomous_schedule_enabled,
)
from ..storage import maintenance_runs as maintenance_store
from ..tasks.autonomous.upkeep import (
    ROUTINE_UPKEEP_WORKFLOW,
    get_routine_upkeep_settings,
    run_routine_upkeep,
)
from .autonomous_models import (
    VALID_QUALITY_GATE_MODES,
    VALID_QUALITY_GATE_TOOLS,
    VALID_TASK_TYPES,
    AutonomousSettings,
    AutonomousSettingsUpdate,
)
from .autonomous_service import (
    get_autonomous_settings as _get_settings,
)
from .autonomous_service import (
    update_autonomous_settings as _update_settings,
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


def _make_dispatch_callback() -> Any:
    from ..workflows.pipeline import _make_dispatch_callback as make_callback

    return make_callback()


def _validate_update(update: AutonomousSettingsUpdate) -> None:
    """Validate all fields of an autonomous settings update request."""
    if update.auto_merge_tiers is not None:
        for tier in update.auto_merge_tiers:
            if tier < 1 or tier > 4:
                raise HTTPException(status_code=400, detail=f"Invalid tier {tier}. Tiers must be 1-4.")

    if update.allowed_types is not None:
        for task_type in update.allowed_types:
            if task_type not in VALID_TASK_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid task type '{task_type}'. Must be one of: {', '.join(VALID_TASK_TYPES)}",
                )

    if update.max_tasks_per_day is not None and update.max_tasks_per_day < 1:
        raise HTTPException(status_code=400, detail="max_tasks_per_day must be at least 1 (or null for unlimited)")

    if update.quality_gate_tools is not None:
        for tool in update.quality_gate_tools:
            if tool not in VALID_QUALITY_GATE_TOOLS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid quality gate tool '{tool}'. Must be one of: {', '.join(VALID_QUALITY_GATE_TOOLS)}",
                )

    if update.quality_gate_mode is not None and update.quality_gate_mode not in VALID_QUALITY_GATE_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid quality gate mode '{update.quality_gate_mode}'. Must be one of: {', '.join(VALID_QUALITY_GATE_MODES)}",
        )


@router.get("/{project_id}/autonomous/settings", response_model=AutonomousSettings)
async def get_settings(project_id: str) -> AutonomousSettings:
    """Get autonomous execution settings for a project."""
    validate_project_exists(project_id)
    return _get_settings(project_id)


@router.patch("/{project_id}/autonomous/settings", response_model=AutonomousSettings)
async def update_settings(project_id: str, update: AutonomousSettingsUpdate) -> AutonomousSettings:
    """Update autonomous execution settings for a project."""
    validate_project_exists(project_id)
    _validate_update(update)
    return _update_settings(project_id, update)


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
    """Enable or disable a single SummitFlow scheduled workflow."""
    validate_project_exists(project_id)
    try:
        payload = set_autonomous_schedule_enabled(project_id, schedule_id, enabled=update.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown autonomous schedule '{schedule_id}'") from exc
    return AutonomousScheduleResponse(**payload)


@router.post("/{project_id}/autonomous/upkeep/run", response_model=RoutineUpkeepRunResponse)
async def run_upkeep(project_id: str) -> RoutineUpkeepRunResponse:
    """Run one routine upkeep cycle immediately."""
    validate_project_exists(project_id)
    dispatch = _make_dispatch_callback()
    result = await asyncio.to_thread(
        run_routine_upkeep,
        project_id,
        dispatch=dispatch,
        force=True,
    )
    return RoutineUpkeepRunResponse(**result)
