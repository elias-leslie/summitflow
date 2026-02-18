"""Autonomous execution settings API."""

from fastapi import APIRouter, HTTPException

from .autonomous_models import (
    VALID_MODEL_TIERS,
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

    if update.preferred_model_tier is not None and update.preferred_model_tier not in VALID_MODEL_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model tier '{update.preferred_model_tier}'. Must be one of: {', '.join(VALID_MODEL_TIERS)}",
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
