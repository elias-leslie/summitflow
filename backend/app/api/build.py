"""Build API - TDD build orchestration endpoints.

Endpoints:
- POST /projects/{project_id}/build/start - Start a TDD build
- GET /projects/{project_id}/build/status - Get current build status
- POST /projects/{project_id}/build/stop - Stop current build
- POST /projects/{project_id}/build/capability - Build a single capability
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.build import get_escalations
from ..services.build_orchestrator import (
    build_capability,
    get_build_status,
    run_full_build,
    start_build,
    stop_build,
)

router = APIRouter(prefix="/projects/{project_id}/build", tags=["build"])


class StartBuildRequest(BaseModel):
    """Request to start a TDD build."""

    component_id: int | None = None
    agent_type: str = "claude"


class StartBuildResponse(BaseModel):
    """Response from starting a build."""

    session_id: str
    project_id: str
    agent_type: str
    capabilities_to_build: list[str]
    total_capabilities: int


class BuildStatusResponse(BaseModel):
    """Current build status."""

    session_id: str | None
    status: str
    current_capability: str | None = None
    capabilities_total: int = 0
    capabilities_completed: int = 0
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    progress_percent: int = 0


class BuildCapabilityRequest(BaseModel):
    """Request to build a single capability."""

    capability_id: str
    session_id: str | None = None


class BuildCapabilityResponse(BaseModel):
    """Response from building a capability."""

    capability_id: str
    status: str
    attempts: int | None = None
    tests_run: int | None = None
    tests_passed: int | None = None
    failure_info: dict | None = None
    reason: str | None = None


class StopBuildResponse(BaseModel):
    """Response from stopping a build."""

    success: bool
    message: str
    final_status: BuildStatusResponse | None = None


@router.post("/start", response_model=StartBuildResponse)
async def api_start_build(
    project_id: str,
    request: StartBuildRequest,
):
    """Start a new TDD build for the project.

    This creates a build session and identifies all capabilities that need work
    (status != 'passing' and not locked).
    """
    try:
        result = await start_build(
            project_id=project_id,
            component_id=request.component_id,
            agent_type=request.agent_type,
        )
        return StartBuildResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status", response_model=BuildStatusResponse)
async def api_get_build_status(project_id: str):
    """Get the current build status for the project.

    Returns the status of any running build, or status='idle' if no build is active.
    """
    status = get_build_status(project_id)
    if status:
        return BuildStatusResponse(**status.to_dict())
    return BuildStatusResponse(session_id=None, status="idle")


@router.post("/stop", response_model=StopBuildResponse)
async def api_stop_build(project_id: str):
    """Stop the current build for the project.

    Gracefully stops the build and returns the final status.
    """
    result = stop_build(project_id)
    if result:
        return StopBuildResponse(
            success=True,
            message="Build stopped successfully",
            final_status=BuildStatusResponse(**result),
        )
    return StopBuildResponse(
        success=False,
        message="No active build to stop",
        final_status=None,
    )


@router.post("/capability", response_model=BuildCapabilityResponse)
async def api_build_capability(
    project_id: str,
    request: BuildCapabilityRequest,
):
    """Build a single capability using the TDD loop.

    If no session_id is provided, a new session will be created.
    """
    session_id = request.session_id

    # If no session, start a temporary one
    if not session_id:
        try:
            start_result = await start_build(project_id)
            session_id = start_result["session_id"]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        result = await build_capability(
            project_id=project_id,
            session_id=session_id,
            capability_id=request.capability_id,
        )
        return BuildCapabilityResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/run")
async def api_run_full_build(
    project_id: str,
    request: StartBuildRequest,
):
    """Run a complete build for all failing capabilities.

    This is a long-running operation that will build all capabilities
    that need work in priority order.
    """
    try:
        result = await run_full_build(
            project_id=project_id,
            component_id=request.component_id,
            agent_type=request.agent_type,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class EscalationResponse(BaseModel):
    """An escalation record."""

    capability_id: str | None
    reason: str | None
    escalated_at: str | None


@router.get("/escalations", response_model=list[EscalationResponse])
async def api_get_escalations(
    project_id: str,
    session_id: str,
):
    """Get escalations for a build session.

    Returns list of escalated capabilities and their reasons.
    """
    escalations = get_escalations(project_id, session_id)
    return [EscalationResponse(**e) for e in escalations]
