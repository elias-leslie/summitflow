"""API endpoints for first-class design asset workflows."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..services.design_asset_pipeline import export_sprite_sheet_frames, generate_asset_image
from ..storage import design_assets
from .design_assets_models import (
    DesignAssetExportResponse,
    DesignAssetListResponse,
    DesignAssetResponse,
    DesignAssetStatsResponse,
    GenerateDesignAssetRequest,
    GenerateDesignAssetResponse,
    UpdateDesignAssetStatusRequest,
)
from .design_assets_utils import asset_to_response, export_to_response
from .mockups_validation import validate_mockup_path

router = APIRouter(tags=["design-assets"])


@router.get("/projects/{project_id}/design-assets", response_model=DesignAssetListResponse)
async def list_design_assets(
    project_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    asset_type: str | None = Query(None),
    workflow: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    tag: str | None = Query(None),
) -> DesignAssetListResponse:
    """List first-class design assets."""
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
        items=[asset_to_response(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/projects/{project_id}/design-assets/stats", response_model=DesignAssetStatsResponse)
async def get_design_asset_stats(project_id: str) -> DesignAssetStatsResponse:
    """Return aggregate asset stats."""
    return DesignAssetStatsResponse(**design_assets.get_asset_stats(project_id))


@router.get("/projects/{project_id}/design-assets/{asset_id}", response_model=DesignAssetResponse)
async def get_design_asset(project_id: str, asset_id: str) -> DesignAssetResponse:
    """Fetch a single asset."""
    asset = design_assets.get_asset(project_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Design asset not found")
    return asset_to_response(asset)


@router.get("/projects/{project_id}/design-assets/{asset_id}/image")
async def get_design_asset_image(project_id: str, asset_id: str) -> FileResponse:
    """Serve the asset image."""
    asset = design_assets.get_asset(project_id, asset_id)
    if not asset or not asset.get("file_path"):
        raise HTTPException(status_code=404, detail="Design asset image not found")
    image_path = validate_mockup_path(asset["file_path"])
    media_type = f"image/{image_path.suffix.lstrip('.') or 'png'}"
    return FileResponse(path=image_path, media_type=media_type, filename=image_path.name)


@router.get(
    "/projects/{project_id}/design-assets/{asset_id}/exports",
    response_model=list[DesignAssetExportResponse],
)
async def list_design_asset_exports(project_id: str, asset_id: str) -> list[DesignAssetExportResponse]:
    """List exports for an asset."""
    return [
        export_to_response(item)
        for item in design_assets.list_asset_exports(project_id, asset_id)
    ]


@router.post(
    "/projects/{project_id}/design-assets/generate",
    response_model=GenerateDesignAssetResponse,
)
async def generate_design_assets(
    project_id: str,
    request: GenerateDesignAssetRequest,
) -> GenerateDesignAssetResponse:
    """Generate one or more design assets."""
    start_time = time.monotonic()
    created_assets = []
    try:
        for index in range(request.variant_count):
            created_assets.append(
                generate_asset_image(
                    project_id=project_id,
                    asset_type=request.asset_type,
                    workflow=request.workflow,
                    name=request.name if request.variant_count == 1 else f"{request.name} v{index + 1}",
                    description=request.description,
                    prompt=request.prompt,
                    style_prompt=request.style_prompt,
                    negative_prompt=request.negative_prompt,
                    background=request.background,
                    transparent_background=request.transparent_background,
                    size=request.size,
                    agent_slug=request.agent_slug,
                    model=request.model,
                    source_asset_id=request.source_asset_id,
                    sheet_columns=request.sheet_columns,
                    sheet_rows=request.sheet_rows,
                    frame_width=request.frame_width,
                    frame_height=request.frame_height,
                    animation_labels=request.animation_labels,
                    tags=request.tags,
                    metadata={"variant_index": index + 1, "variant_count": request.variant_count},
                    reference_image=request.reference_image,
                    reference_mime_type=request.reference_mime_type,
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Asset generation failed: {exc}") from exc

    generation_time_ms = int((time.monotonic() - start_time) * 1000)
    return GenerateDesignAssetResponse(
        success=True,
        assets=[asset_to_response(asset) for asset in created_assets],
        generation_time_ms=generation_time_ms,
    )


@router.post(
    "/projects/{project_id}/design-assets/{asset_id}/exports/sprite-frames",
    response_model=DesignAssetExportResponse,
)
async def create_sprite_frame_export(
    project_id: str,
    asset_id: str,
) -> DesignAssetExportResponse:
    """Slice a sprite sheet into production-ready frame exports."""
    asset = design_assets.get_asset(project_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Design asset not found")
    try:
        export_record = export_sprite_sheet_frames(asset)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return export_to_response(export_record)


@router.put(
    "/projects/{project_id}/design-assets/{asset_id}/status",
    response_model=DesignAssetResponse,
)
async def update_design_asset_status(
    project_id: str,
    asset_id: str,
    request: UpdateDesignAssetStatusRequest,
) -> DesignAssetResponse:
    """Update asset lifecycle status."""
    try:
        asset = design_assets.update_asset_status(
            project_id,
            asset_id,
            request.status,
            approved_by=request.approved_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not asset:
        raise HTTPException(status_code=404, detail="Design asset not found")
    return asset_to_response(asset)


@router.delete("/projects/{project_id}/design-assets/{asset_id}")
async def delete_design_asset(project_id: str, asset_id: str) -> dict[str, bool]:
    """Delete an asset and its exports."""
    deleted = design_assets.delete_asset(project_id, asset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Design asset not found")
    return {"deleted": True}
