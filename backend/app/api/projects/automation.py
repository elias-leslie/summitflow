"""Automation settings endpoints for projects."""

from fastapi import APIRouter, HTTPException

from ...storage.connection import get_connection
from .models import DEFAULT_AUTOMATION_SETTINGS, AutomationSettings

router = APIRouter()


@router.get("/{project_id}/settings/automation", response_model=AutomationSettings)
async def get_automation_settings(project_id: str) -> AutomationSettings:
    """Get automation settings for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT automation_settings FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    settings = row[0] or DEFAULT_AUTOMATION_SETTINGS
    return AutomationSettings(**settings)


@router.put("/{project_id}/settings/automation", response_model=AutomationSettings)
async def update_automation_settings(
    project_id: str, settings: AutomationSettings
) -> AutomationSettings:
    """Update automation settings for a project."""
    # Validate agents
    if settings.primary_agent not in ("claude", "gemini"):
        raise HTTPException(status_code=400, detail="primary_agent must be 'claude' or 'gemini'")
    if settings.secondary_agent not in ("claude", "gemini"):
        raise HTTPException(status_code=400, detail="secondary_agent must be 'claude' or 'gemini'")

    # Validate budget
    if settings.daily_budget_usd < 0:
        raise HTTPException(status_code=400, detail="daily_budget_usd cannot be negative")

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        cur.execute(
            "UPDATE projects SET automation_settings = %s WHERE id = %s",
            (settings.model_dump_json(), project_id),
        )
        conn.commit()

    return settings
