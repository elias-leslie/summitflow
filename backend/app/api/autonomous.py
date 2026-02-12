"""Autonomous execution settings API."""

from fastapi import APIRouter, HTTPException

from ..storage.connection import get_connection
from .autonomous_models import (
    AutonomousSettings,
    AutonomousSettingsUpdate,
)
from .autonomous_service import (
    get_autonomous_settings as _get_settings,
)
from .autonomous_service import (
    update_autonomous_settings as _update_settings,
)

router = APIRouter()

# Re-export models for backward compatibility
__all__ = [
    "AutonomousSettings",
    "AutonomousSettingsUpdate",
    "router",
]


def _verify_project_exists(project_id: str) -> None:
    """Verify that a project exists, raising 404 if not."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


@router.get("/{project_id}/autonomous/settings", response_model=AutonomousSettings)
async def get_settings(project_id: str) -> AutonomousSettings:
    """Get autonomous execution settings for a project."""
    _verify_project_exists(project_id)
    return _get_settings(project_id)


@router.patch("/{project_id}/autonomous/settings", response_model=AutonomousSettings)
async def update_settings(project_id: str, update: AutonomousSettingsUpdate) -> AutonomousSettings:
    """Update autonomous execution settings for a project."""
    _verify_project_exists(project_id)

    # Validate auto_merge_tiers
    if update.auto_merge_tiers is not None:
        for tier in update.auto_merge_tiers:
            if tier < 1 or tier > 4:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid tier {tier}. Tiers must be 1-4.",
                )

    return _update_settings(project_id, update)
