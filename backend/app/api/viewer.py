"""Read-only viewer APIs for shared SummitFlow sections."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..access_control import AccessPrincipal, require_authenticated
from ..storage import access as access_store
from ..storage import design_assets
from ..storage import mockups as mockups_storage
from .design_assets import get_design_asset_image
from .design_assets_models import (
    DesignAssetExportResponse,
    DesignAssetListResponse,
    DesignAssetResponse,
    DesignAssetStatsResponse,
)
from .design_assets_utils import asset_to_response, export_to_response
from .mockups_crud import get_mockup_image, get_mockup_screenshot
from .mockups_models import MockupListResponse, MockupResponse, MockupStatsResponse
from .mockups_utils import to_response

router = APIRouter()
AuthenticatedPrincipal = Annotated[AccessPrincipal, Depends(require_authenticated)]


class ViewerProjectResponse(BaseModel):
    id: str
    name: str
    public_url: str | None
    created_at: str | None
    sections: list[str]


def _require_design_access(project_id: str, principal: AccessPrincipal) -> None:
    if principal.is_owner:
        return
    if not principal.is_viewer:
        raise HTTPException(status_code=403, detail="Viewer access required")
    if not access_store.has_project_section_access(principal.email, project_id, "design"):
        raise HTTPException(status_code=403, detail="Design section is not shared")


def _sanitize_mockup(response: MockupResponse) -> MockupResponse:
    return response.model_copy(
        update={
            "file_path": "available" if response.file_path else None,
            "task_id": None,
        }
    )


def _sanitize_asset(response: DesignAssetResponse) -> DesignAssetResponse:
    return response.model_copy(update={"file_path": "available" if response.file_path else None})


def _sanitize_export(response: DesignAssetExportResponse) -> DesignAssetExportResponse:
    return response.model_copy(update={"file_path": "", "manifest_path": None})


@router.get("/projects", response_model=list[ViewerProjectResponse])
def list_viewer_projects(
    principal: AuthenticatedPrincipal,
) -> list[ViewerProjectResponse]:
    """List projects visible to the viewer."""
    if principal.is_owner:
        return []
    projects = []
    for project in access_store.list_viewer_projects(principal.email):
        public_url = project["public_url"] if isinstance(project["public_url"], str) else None
        created = project["created_at"]
        sections = project["sections"]
        projects.append(
            ViewerProjectResponse(
                id=str(project["id"]),
                name=str(project["name"]),
                public_url=public_url,
                created_at=created.isoformat() if isinstance(created, datetime) else None,
                sections=[str(section) for section in sections]
                if isinstance(sections, list | tuple)
                else [],
            )
        )
    return projects


@router.get("/projects/{project_id}/mockups", response_model=MockupListResponse)
def list_mockups(
    project_id: str,
    principal: AuthenticatedPrincipal,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    mockup_type: str | None = Query(None),
    status: str | None = Query(None),
    task_id: str | None = Query(None),
    page_path: str | None = Query(None),
    generator: str | None = Query(None),
    search: str | None = Query(None),
) -> MockupListResponse:
    """List shared mockups for a project."""
    _require_design_access(project_id, principal)
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
        items=[_sanitize_mockup(to_response(item)) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/projects/{project_id}/mockups/stats", response_model=MockupStatsResponse)
def mockup_stats(
    project_id: str,
    principal: AuthenticatedPrincipal,
) -> MockupStatsResponse:
    """Return shared mockup stats."""
    _require_design_access(project_id, principal)
    stats = mockups_storage.get_mockup_stats(project_id)
    return MockupStatsResponse(
        total=stats["total"],
        by_status=stats["by_status"],
        unique_generators=stats["unique_generators"],
        avg_generation_time_ms=stats["avg_generation_time_ms"],
    )


@router.get("/projects/{project_id}/mockups/{mockup_id}", response_model=MockupResponse)
def get_mockup(
    project_id: str,
    mockup_id: str,
    principal: AuthenticatedPrincipal,
) -> MockupResponse:
    """Return one shared mockup."""
    _require_design_access(project_id, principal)
    mockup = mockups_storage.get_mockup(project_id, mockup_id)
    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")
    return _sanitize_mockup(to_response(mockup))


@router.get("/projects/{project_id}/mockups/{mockup_id}/history", response_model=list[MockupResponse])
def mockup_history(
    project_id: str,
    mockup_id: str,
    principal: AuthenticatedPrincipal,
) -> list[MockupResponse]:
    """Return shared mockup history."""
    _require_design_access(project_id, principal)
    history = mockups_storage.get_mockup_history(project_id, mockup_id)
    if not history:
        raise HTTPException(status_code=404, detail="Mockup not found")
    return [_sanitize_mockup(to_response(item)) for item in history]


@router.get("/projects/{project_id}/mockups/{mockup_id}/image")
async def mockup_image(
    project_id: str,
    mockup_id: str,
    principal: AuthenticatedPrincipal,
) -> FileResponse:
    """Return a shared mockup image."""
    _require_design_access(project_id, principal)
    return await get_mockup_image(project_id, mockup_id)


@router.get("/projects/{project_id}/mockups/{mockup_id}/screenshot")
async def mockup_screenshot(
    project_id: str,
    mockup_id: str,
    principal: AuthenticatedPrincipal,
) -> FileResponse:
    """Return a shared mockup screenshot."""
    _require_design_access(project_id, principal)
    return await get_mockup_screenshot(project_id, mockup_id)


@router.get("/projects/{project_id}/design-assets", response_model=DesignAssetListResponse)
def list_assets(
    project_id: str,
    principal: AuthenticatedPrincipal,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    asset_type: str | None = Query(None),
    workflow: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    tag: str | None = Query(None),
) -> DesignAssetListResponse:
    """List shared design assets."""
    _require_design_access(project_id, principal)
    items, total = design_assets.list_assets(
        project_id,
        limit=limit,
        offset=offset,
        asset_type=asset_type,
        workflow=workflow,
        status=status,
        search=search,
        tag=tag,
    )
    return DesignAssetListResponse(
        items=[_sanitize_asset(asset_to_response(item)) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/projects/{project_id}/design-assets/stats", response_model=DesignAssetStatsResponse)
def asset_stats(
    project_id: str,
    principal: AuthenticatedPrincipal,
) -> DesignAssetStatsResponse:
    """Return shared design asset stats."""
    _require_design_access(project_id, principal)
    return DesignAssetStatsResponse(**design_assets.get_asset_stats(project_id))


@router.get("/projects/{project_id}/design-assets/{asset_id}", response_model=DesignAssetResponse)
def get_asset(
    project_id: str,
    asset_id: str,
    principal: AuthenticatedPrincipal,
) -> DesignAssetResponse:
    """Return one shared design asset."""
    _require_design_access(project_id, principal)
    asset = design_assets.get_asset(project_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Design asset not found")
    return _sanitize_asset(asset_to_response(asset))


@router.get("/projects/{project_id}/design-assets/{asset_id}/image")
async def asset_image(
    project_id: str,
    asset_id: str,
    principal: AuthenticatedPrincipal,
) -> FileResponse:
    """Return a shared design asset image."""
    _require_design_access(project_id, principal)
    return await get_design_asset_image(project_id, asset_id)


@router.get(
    "/projects/{project_id}/design-assets/{asset_id}/exports",
    response_model=list[DesignAssetExportResponse],
)
def asset_exports(
    project_id: str,
    asset_id: str,
    principal: AuthenticatedPrincipal,
) -> list[DesignAssetExportResponse]:
    """Return sanitized export records for a shared asset."""
    _require_design_access(project_id, principal)
    return [
        _sanitize_export(export_to_response(item))
        for item in design_assets.list_asset_exports(project_id, asset_id)
    ]
