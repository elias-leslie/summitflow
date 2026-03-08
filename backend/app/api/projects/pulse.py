"""Project pulse API for cross-agent coordination."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...services.project_pulse import build_project_pulse

router = APIRouter()


@router.get("/{project_id}/pulse")
async def get_project_pulse(project_id: str) -> dict[str, Any]:
    """Return the canonical live coordination pulse for a project."""
    return await build_project_pulse(project_id)
