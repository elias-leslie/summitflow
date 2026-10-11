"""Project pulse API for cross-agent coordination."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ...services.project_pulse import AgentHubUnavailableError, build_project_pulse

router = APIRouter()


def _compact_pulse(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": payload.get("project_id"),
        "generated_at": payload.get("generated_at"),
        "summary": payload.get("summary", {}),
        "cleanup": payload.get("cleanup", {}),
    }


@router.get("/{project_id}/pulse")
async def get_project_pulse(project_id: str, compact: bool = False) -> dict[str, Any]:
    """Return the canonical live coordination pulse for a project."""
    try:
        payload = await build_project_pulse(project_id)
    except AgentHubUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _compact_pulse(payload) if compact else payload
