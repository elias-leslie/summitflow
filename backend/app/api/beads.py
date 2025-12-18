"""Beads API endpoints for SummitFlow.

Provides REST API for bead management via bd CLI wrapper.
Beads stay in project .beads/ directory (JSONL), NOT in PostgreSQL.
"""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.beads_service import BeadsService
from app.storage.connection import get_connection

router = APIRouter(tags=["beads"])


# Pydantic Models
class BeadInfo(BaseModel):
    """Bead information."""

    id: str = Field(..., description="Bead ID")
    title: str = Field(..., description="Bead title")
    description: str | None = Field(None, description="Bead description")
    notes: str | None = Field(None, description="Notes/comments")
    status: str = Field(..., description="Status: open, in_progress, closed")
    priority: int = Field(..., description="Priority level (0-4)")
    issue_type: str = Field(..., description="Type: task, bug, feature, epic")
    labels: list[str] | None = Field(None, description="Labels")
    created_at: str | None = Field(None, description="Creation timestamp")
    updated_at: str | None = Field(None, description="Last update timestamp")
    closed_at: str | None = Field(None, description="Closure timestamp")
    dependency_count: int | None = Field(None, description="Number of dependencies")
    dependent_count: int | None = Field(None, description="Number of dependents")


class BeadListResponse(BaseModel):
    """Response for bead list."""

    beads: list[BeadInfo] = Field(..., description="List of beads")
    total: int = Field(..., description="Total count")
    stats: dict[str, Any] = Field(default_factory=dict, description="Statistics")


class BeadCreateRequest(BaseModel):
    """Request to create a new bead."""

    title: str = Field(..., description="Bead title")
    description: str | None = Field(None, description="Bead description")
    priority: int = Field(2, ge=0, le=4, description="Priority (0=critical, 4=backlog)")
    issue_type: str = Field("task", description="Type: task, bug, feature, epic")
    labels: list[str] | None = Field(None, description="Labels to apply")


class BeadUpdateRequest(BaseModel):
    """Request to update a bead."""

    status: str | None = Field(None, description="New status")
    priority: int | None = Field(None, ge=0, le=4, description="New priority")
    title: str | None = Field(None, description="New title")
    notes: str | None = Field(None, description="Notes to add")
    labels: list[str] | None = Field(None, description="Labels to set")


class BeadCloseRequest(BaseModel):
    """Request to close a bead."""

    reason: str = Field(..., description="Closure reason")


class BeadStatsResponse(BaseModel):
    """Statistics response."""

    total: int = Field(..., description="Total beads")
    open: int = Field(..., description="Open beads")
    closed: int = Field(..., description="Closed beads")
    in_progress: int = Field(..., description="In progress beads")
    by_priority: dict[int, int] = Field(default_factory=dict, description="Counts by priority")
    by_type: dict[str, int] = Field(default_factory=dict, description="Counts by type")


def _get_project_path(project_id: str) -> str:
    """Get the root_path for a project from the database.

    Args:
        project_id: The project ID

    Returns:
        The project's root_path

    Raises:
        HTTPException: If project not found or has no root_path
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT root_path FROM projects WHERE id = %s",
            [project_id],
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        root_path = row[0]
        if not root_path:
            raise HTTPException(
                status_code=400,
                detail=f"Project {project_id} has no root_path configured",
            )

        return root_path


def _get_beads_service(project_id: str) -> BeadsService:
    """Get a BeadsService for a project."""
    root_path = _get_project_path(project_id)
    service = BeadsService(root_path)

    if not service.has_beads():
        raise HTTPException(
            status_code=404,
            detail=f"Project {project_id} has no .beads/ directory",
        )

    return service


# API Endpoints
@router.get("/projects/{project_id}/beads", response_model=BeadListResponse)
def list_beads(
    project_id: str,
    status: Literal["all", "open", "closed"] | None = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=500, description="Maximum beads to return"),
) -> BeadListResponse:
    """List beads for a project.

    Args:
        project_id: The project ID
        status: Optional status filter
        limit: Maximum number of beads

    Returns:
        List of beads with statistics
    """
    service = _get_beads_service(project_id)
    result = service.list_beads(status=status or "all", limit=limit)

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    beads = result.data or []
    stats = service.get_stats()

    return BeadListResponse(
        beads=[BeadInfo(**b) for b in beads],
        total=len(beads),
        stats=stats,
    )


@router.get("/projects/{project_id}/beads/ready", response_model=BeadListResponse)
def get_ready_beads(project_id: str) -> BeadListResponse:
    """Get beads ready for work (no blockers).

    Args:
        project_id: The project ID

    Returns:
        List of ready beads
    """
    service = _get_beads_service(project_id)
    result = service.get_ready()

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    beads = result.data or []

    return BeadListResponse(
        beads=[BeadInfo(**b) for b in beads],
        total=len(beads),
        stats={},
    )


@router.get("/projects/{project_id}/beads/stats", response_model=BeadStatsResponse)
def get_bead_stats(project_id: str) -> BeadStatsResponse:
    """Get bead statistics for a project.

    Args:
        project_id: The project ID

    Returns:
        Statistics about beads
    """
    service = _get_beads_service(project_id)
    stats = service.get_stats()

    return BeadStatsResponse(**stats)


@router.get("/projects/{project_id}/beads/{bead_id}", response_model=BeadInfo)
def get_bead(project_id: str, bead_id: str) -> BeadInfo:
    """Get a single bead by ID.

    Args:
        project_id: The project ID
        bead_id: The bead ID

    Returns:
        Bead details
    """
    service = _get_beads_service(project_id)
    result = service.get_bead(bead_id)

    if not result.success:
        raise HTTPException(status_code=404, detail=result.error or "Bead not found")

    return BeadInfo(**result.data)


@router.post("/projects/{project_id}/beads", response_model=BeadInfo)
def create_bead(project_id: str, request: BeadCreateRequest) -> BeadInfo:
    """Create a new bead.

    Args:
        project_id: The project ID
        request: Bead creation request

    Returns:
        Created bead
    """
    service = _get_beads_service(project_id)
    result = service.create_bead(
        title=request.title,
        description=request.description,
        priority=request.priority,
        issue_type=request.issue_type,
        labels=request.labels,
    )

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    # bd create returns array, get first item
    data = result.data
    if isinstance(data, list) and len(data) > 0:
        data = data[0]

    return BeadInfo(**data)


@router.patch("/projects/{project_id}/beads/{bead_id}", response_model=BeadInfo)
def update_bead(project_id: str, bead_id: str, request: BeadUpdateRequest) -> BeadInfo:
    """Update an existing bead.

    Args:
        project_id: The project ID
        bead_id: The bead ID
        request: Update request

    Returns:
        Updated bead
    """
    service = _get_beads_service(project_id)
    result = service.update_bead(
        bead_id=bead_id,
        status=request.status,
        priority=request.priority,
        title=request.title,
        notes=request.notes,
        labels=request.labels,
    )

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    # bd update returns array, get first item
    data = result.data
    if isinstance(data, list) and len(data) > 0:
        data = data[0]

    return BeadInfo(**data)


@router.post("/projects/{project_id}/beads/{bead_id}/close", response_model=BeadInfo)
def close_bead(project_id: str, bead_id: str, request: BeadCloseRequest) -> BeadInfo:
    """Close a bead with a reason.

    Args:
        project_id: The project ID
        bead_id: The bead ID
        request: Close request with reason

    Returns:
        Closed bead
    """
    service = _get_beads_service(project_id)
    result = service.close_bead(bead_id=bead_id, reason=request.reason)

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    # bd close returns array, get first item
    data = result.data
    if isinstance(data, list) and len(data) > 0:
        data = data[0]

    return BeadInfo(**data)
