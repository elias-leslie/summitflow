"""Task and page-scoped endpoints for mockups API."""

from fastapi import APIRouter, Query

from ..storage import mockups as mockups_storage
from .mockups_models import MockupResponse
from .mockups_utils import to_response

router = APIRouter()


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
    return [to_response(m) for m in mockups]


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
    return [to_response(m) for m in mockups]
