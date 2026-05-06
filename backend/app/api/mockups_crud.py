"""CRUD endpoints for mockups API."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..storage import mockups as mockups_storage
from .mockups_models import (
    MockupContextResponse,
    MockupCreate,
    MockupListResponse,
    MockupResponse,
    MockupStatsResponse,
    MockupStatusUpdate,
    MockupUpdate,
)
from .mockups_utils import compact_context_for_mockup, to_response
from .mockups_validation import validate_mockup_path

router = APIRouter()


@router.post(
    "/projects/{project_id}/mockups",
    response_model=MockupResponse,
    status_code=201,
)
async def create_mockup(
    project_id: str,
    request: MockupCreate,
) -> MockupResponse:
    """Create a new mockup with provenance metadata tracking."""
    if request.file_path:
        validate_mockup_path(request.file_path)

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
            metadata=request.metadata,
        )
        return to_response(mockup)
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
        items=[to_response(m) for m in items],
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
    return to_response(mockup)


@router.get(
    "/projects/{project_id}/mockups/{mockup_id}/context",
    response_model=MockupContextResponse,
)
async def get_mockup_context(
    project_id: str,
    mockup_id: str,
    include_content: bool = Query(False, description="Include full HTML content"),
) -> MockupContextResponse:
    """Get compact mockup context for Work Chats and agents."""
    mockup = mockups_storage.get_mockup(project_id, mockup_id)
    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")
    return compact_context_for_mockup(mockup, include_content=include_content)


@router.get("/projects/{project_id}/mockups/{mockup_id}/image")
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

    image_path = validate_mockup_path(file_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(
        path=image_path,
        media_type="image/png",
        filename=f"{mockup_id}.png",
    )


@router.get("/projects/{project_id}/mockups/{mockup_id}/screenshot")
async def get_mockup_screenshot(
    project_id: str,
    mockup_id: str,
) -> FileResponse:
    """Get the original screenshot for a design-analyzer mockup.

    For mockups generated by design-analyzer, returns the original page
    screenshot that was analyzed. The screenshot is stored alongside
    the mockup image with filename 'screenshot.png'.

    Returns 404 if:
    - Mockup doesn't exist
    - Mockup has no file_path
    - Mockup wasn't generated by design-analyzer
    - Screenshot file doesn't exist
    """
    mockup = mockups_storage.get_mockup(project_id, mockup_id)
    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")

    if mockup.get("generator") != "design-analyzer":
        raise HTTPException(
            status_code=404,
            detail="Screenshots only available for design-analyzer mockups",
        )

    file_path = mockup.get("file_path")
    if not file_path:
        raise HTTPException(status_code=404, detail="Mockup has no file path")

    validated_path = validate_mockup_path(file_path)
    screenshot_path = validated_path.parent / "screenshot.png"

    if not screenshot_path.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")

    return FileResponse(
        path=screenshot_path,
        media_type="image/png",
        filename=f"{mockup_id}-screenshot.png",
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
    return [to_response(m) for m in history]


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
    if request.file_path:
        validate_mockup_path(request.file_path)

    mockup = mockups_storage.update_mockup(
        project_id=project_id,
        mockup_id=mockup_id,
        name=request.name,
        description=request.description,
        file_path=request.file_path,
        content=request.content,
        page_path=request.page_path,
        metadata=request.metadata,
    )
    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")
    return to_response(mockup)


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
        return to_response(mockup)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/projects/{project_id}/mockups/{mockup_id}")
async def delete_mockup(
    project_id: str,
    mockup_id: str,
) -> dict[str, Any]:
    """Delete a mockup."""
    deleted = mockups_storage.delete_mockup(project_id, mockup_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Mockup not found")
    return {"deleted": True, "mockup_id": mockup_id}
