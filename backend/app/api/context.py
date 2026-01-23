"""Context API - Project auto-detection and working context.

Handles:
- Project detection from X-Cwd header
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ..storage.projects import find_project_by_cwd

router = APIRouter(prefix="/context", tags=["context"])


class ProjectContextResponse(BaseModel):
    """Response for project auto-detection."""

    project_id: str
    name: str
    root_path: str


@router.get("/project", response_model=ProjectContextResponse)
async def detect_project(
    x_cwd: str = Header(None, alias="X-Cwd", description="Current working directory"),
) -> ProjectContextResponse:
    """Auto-detect project from current working directory.

    Reads the X-Cwd header and matches it to a registered project's root_path.
    Returns the most specific match (longest root_path prefix).

    Args:
        x_cwd: Current working directory passed via X-Cwd header

    Returns:
        Project context with id, name, and root_path

    Raises:
        HTTPException(400): If X-Cwd header is missing
        HTTPException(404): If no project matches the cwd
    """
    if not x_cwd:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "X-Cwd header is required",
                "hint": "Pass current working directory in X-Cwd header",
            },
        )

    project = find_project_by_cwd(x_cwd)
    if not project:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"No project found for cwd: {x_cwd}",
                "hint": "Register the project first or check the path",
            },
        )

    return ProjectContextResponse(
        project_id=project["id"],
        name=project["name"],
        root_path=project["root_path"],
    )
