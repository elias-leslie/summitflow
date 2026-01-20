"""Mockups API endpoints.

Provides CRUD operations for design mockups:
- Create, read, update, delete mockups
- List mockups with filtering
- Approval workflow
- Mockup history/iterations
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..storage import mockups as mockups_storage

router = APIRouter(tags=["mockups"])


# ============================================================
# Request/Response Models
# ============================================================


class MockupCreate(BaseModel):
    """Request to create a mockup."""

    name: str
    description: str | None = None
    mockup_type: str = "component"
    file_path: str | None = None
    content: str | None = None
    task_id: str | None = None
    page_path: str | None = None
    parent_mockup_id: int | None = None
    generator: str | None = None
    generation_prompt: str | None = None
    generation_time_ms: int | None = None


class MockupUpdate(BaseModel):
    """Request to update a mockup."""

    name: str | None = None
    description: str | None = None
    file_path: str | None = None
    content: str | None = None
    page_path: str | None = None


class MockupStatusUpdate(BaseModel):
    """Request to update mockup status."""

    status: str
    approved_by: str | None = None


class MockupResponse(BaseModel):
    """Response model for a mockup."""

    id: int
    project_id: str
    mockup_id: str
    name: str
    description: str | None
    mockup_type: str
    file_path: str | None
    content: str | None
    status: str
    approved_at: str | None
    approved_by: str | None
    applied_at: str | None
    task_id: str | None
    page_path: str | None
    version: int
    parent_mockup_id: int | None
    generator: str | None
    generation_prompt: str | None
    generation_time_ms: int | None
    iteration_count: int
    created_at: str | None
    updated_at: str | None


class MockupListResponse(BaseModel):
    """Response for mockup list endpoint."""

    items: list[MockupResponse]
    total: int
    limit: int
    offset: int


class MockupStatsResponse(BaseModel):
    """Response for mockup statistics."""

    total: int
    by_status: dict[str, int]
    unique_generators: int
    avg_generation_time_ms: float | None


def _to_response(mockup: dict[str, Any]) -> MockupResponse:
    """Convert storage dict to response model."""
    return MockupResponse(
        id=mockup["id"],
        project_id=mockup["project_id"],
        mockup_id=mockup["mockup_id"],
        name=mockup["name"],
        description=mockup["description"],
        mockup_type=mockup["mockup_type"],
        file_path=mockup["file_path"],
        content=mockup["content"],
        status=mockup["status"],
        approved_at=mockup["approved_at"],
        approved_by=mockup["approved_by"],
        applied_at=mockup["applied_at"],
        task_id=mockup["task_id"],
        page_path=mockup["page_path"],
        version=mockup["version"],
        parent_mockup_id=mockup["parent_mockup_id"],
        generator=mockup["generator"],
        generation_prompt=mockup["generation_prompt"],
        generation_time_ms=mockup["generation_time_ms"],
        iteration_count=mockup["iteration_count"],
        created_at=mockup["created_at"],
        updated_at=mockup["updated_at"],
    )


# ============================================================
# CRUD Endpoints
# ============================================================


@router.post(
    "/projects/{project_id}/mockups",
    response_model=MockupResponse,
    status_code=201,
)
async def create_mockup(
    project_id: str,
    request: MockupCreate,
) -> MockupResponse:
    """Create a new mockup.

    Creates a mockup record with provenance metadata tracking.
    """
    try:
        mockup = mockups_storage.create_mockup(
            project_id=project_id,
            name=request.name,
            description=request.description,
            mockup_type=request.mockup_type,
            file_path=request.file_path,
            content=request.content,
            task_id=request.task_id,
            page_path=request.page_path,
            parent_mockup_id=request.parent_mockup_id,
            generator=request.generator,
            generation_prompt=request.generation_prompt,
            generation_time_ms=request.generation_time_ms,
        )
        return _to_response(mockup)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get(
    "/projects/{project_id}/mockups",
    response_model=MockupListResponse,
)
async def list_mockups(
    project_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    mockup_type: str | None = Query(None, description="Filter by type"),
    status: str | None = Query(None, description="Filter by status"),
    task_id: str | None = Query(None, description="Filter by task"),
    page_path: str | None = Query(None, description="Filter by page path"),
    generator: str | None = Query(None, description="Filter by generator"),
    search: str | None = Query(None, description="Search in name/description"),
) -> MockupListResponse:
    """List mockups for a project with filtering."""
    items, total = mockups_storage.list_mockups(
        project_id=project_id,
        limit=limit,
        offset=offset,
        mockup_type=mockup_type,
        status=status,
        task_id=task_id,
        page_path=page_path,
        generator=generator,
        search=search,
    )
    return MockupListResponse(
        items=[_to_response(m) for m in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/projects/{project_id}/mockups/stats",
    response_model=MockupStatsResponse,
)
async def get_mockup_stats(project_id: str) -> MockupStatsResponse:
    """Get mockup statistics for a project."""
    stats = mockups_storage.get_mockup_stats(project_id)
    return MockupStatsResponse(
        total=stats["total"],
        by_status=stats["by_status"],
        unique_generators=stats["unique_generators"],
        avg_generation_time_ms=stats["avg_generation_time_ms"],
    )


@router.get(
    "/projects/{project_id}/mockups/{mockup_id}",
    response_model=MockupResponse,
)
async def get_mockup(
    project_id: str,
    mockup_id: str,
) -> MockupResponse:
    """Get a mockup by ID."""
    mockup = mockups_storage.get_mockup(project_id, mockup_id)
    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")
    return _to_response(mockup)


@router.get(
    "/projects/{project_id}/mockups/{mockup_id}/image",
)
async def get_mockup_image(
    project_id: str,
    mockup_id: str,
) -> FileResponse:
    """Get the mockup image file."""
    mockup = mockups_storage.get_mockup(project_id, mockup_id)
    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")

    file_path = mockup.get("file_path")
    if not file_path:
        raise HTTPException(status_code=404, detail="Mockup has no image file")

    image_path = Path(file_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(
        path=image_path,
        media_type="image/png",
        filename=f"{mockup_id}.png",
    )


@router.get(
    "/projects/{project_id}/mockups/{mockup_id}/history",
    response_model=list[MockupResponse],
)
async def get_mockup_history(
    project_id: str,
    mockup_id: str,
) -> list[MockupResponse]:
    """Get the iteration history of a mockup."""
    history = mockups_storage.get_mockup_history(project_id, mockup_id)
    if not history:
        raise HTTPException(status_code=404, detail="Mockup not found")
    return [_to_response(m) for m in history]


@router.put(
    "/projects/{project_id}/mockups/{mockup_id}",
    response_model=MockupResponse,
)
async def update_mockup(
    project_id: str,
    mockup_id: str,
    request: MockupUpdate,
) -> MockupResponse:
    """Update a mockup's non-provenance fields."""
    mockup = mockups_storage.update_mockup(
        project_id=project_id,
        mockup_id=mockup_id,
        name=request.name,
        description=request.description,
        file_path=request.file_path,
        content=request.content,
        page_path=request.page_path,
    )
    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")
    return _to_response(mockup)


@router.put(
    "/projects/{project_id}/mockups/{mockup_id}/status",
    response_model=MockupResponse,
)
async def update_mockup_status(
    project_id: str,
    mockup_id: str,
    request: MockupStatusUpdate,
) -> MockupResponse:
    """Update a mockup's status.

    Status transitions:
    - generated -> pending_approval (submit for review)
    - pending_approval -> approved (approve) or rejected (reject)
    - approved -> applied (implementation complete)
    - any -> archived (soft delete)
    """
    try:
        mockup = mockups_storage.update_mockup_status(
            project_id=project_id,
            mockup_id=mockup_id,
            status=request.status,
            approved_by=request.approved_by,
        )
        if not mockup:
            raise HTTPException(status_code=404, detail="Mockup not found")
        return _to_response(mockup)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete(
    "/projects/{project_id}/mockups/{mockup_id}",
)
async def delete_mockup(
    project_id: str,
    mockup_id: str,
) -> dict[str, Any]:
    """Delete a mockup."""
    deleted = mockups_storage.delete_mockup(project_id, mockup_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Mockup not found")
    return {"deleted": True, "mockup_id": mockup_id}


# ============================================================
# Task-scoped Endpoints
# ============================================================


@router.get(
    "/projects/{project_id}/tasks/{task_id}/mockups",
    response_model=list[MockupResponse],
)
async def get_task_mockups(
    project_id: str,
    task_id: str,
    status: str | None = Query(None, description="Filter by status"),
) -> list[MockupResponse]:
    """Get all mockups for a specific task."""
    mockups = mockups_storage.get_mockups_for_task(project_id, task_id, status)
    return [_to_response(m) for m in mockups]


# ============================================================
# Page-scoped Endpoints
# ============================================================


@router.get(
    "/projects/{project_id}/pages/mockups",
    response_model=list[MockupResponse],
)
async def get_page_mockups(
    project_id: str,
    page_path: str = Query(..., description="Page path to get mockups for"),
    status: str | None = Query(None, description="Filter by status"),
) -> list[MockupResponse]:
    """Get all mockups for a specific page path."""
    mockups = mockups_storage.get_mockups_for_page(project_id, page_path, status)
    return [_to_response(m) for m in mockups]


# ============================================================
# Design Analysis Endpoints
# ============================================================


class AnalyzePageRequest(BaseModel):
    """Request to analyze a page's design."""

    page_url: str
    page_path: str | None = None


class AnalyzePageResponse(BaseModel):
    """Response from page design analysis."""

    success: bool
    mockup_id: str | None = None
    screenshot_path: str | None = None
    mockup_image_path: str | None = None
    recommendations: str | None = None
    issues_found: int = 0
    error: str | None = None
    generation_time_ms: int = 0


@router.post(
    "/projects/{project_id}/mockups/analyze-page",
    response_model=AnalyzePageResponse,
)
async def analyze_page(
    project_id: str,
    request: AnalyzePageRequest,
) -> AnalyzePageResponse:
    """Analyze a page's design and generate improvement recommendations.

    This endpoint:
    1. Captures a screenshot of the specified URL
    2. Analyzes it against the project's design standards
    3. Generates specific improvement recommendations
    4. Stores the result as a mockup record

    The mockup record will contain:
    - The captured screenshot (file_path)
    - The analysis and recommendations (generation_prompt)
    - Metadata about the analysis
    """
    from ..services.mockup_generator import analyze_page_design

    result = await analyze_page_design(
        project_id=project_id,
        page_url=request.page_url,
        page_path=request.page_path,
    )

    return AnalyzePageResponse(
        success=result.success,
        mockup_id=result.mockup_id,
        screenshot_path=result.screenshot_path,
        mockup_image_path=result.mockup_image_path,
        recommendations=result.recommendations,
        issues_found=result.issues_found,
        error=result.error,
        generation_time_ms=result.generation_time_ms,
    )
