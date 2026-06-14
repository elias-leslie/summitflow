"""API endpoints for first-class design asset workflows."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from ..access_control import get_current_principal
from ..services.design_asset_pipeline import (
    export_sprite_sheet_frames,
    generate_asset_image,
    import_asset_image,
)
from ..storage import design_assets
from .design_assets_models import (
    DesignAssetCommentRequest,
    DesignAssetCommentResponse,
    DesignAssetExportResponse,
    DesignAssetListResponse,
    DesignAssetResponse,
    DesignAssetStatsResponse,
    GenerateDesignAssetRequest,
    GenerateDesignAssetResponse,
    ImportDesignAssetRequest,
    RateDesignAssetRequest,
    UpdateDesignAssetStatusRequest,
)
from .design_assets_utils import asset_to_response, export_to_response
from .mockups_validation import validate_mockup_path

router = APIRouter(tags=["design-assets"])

_IMAGE_MEDIA_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def _comment_author(request: Request) -> str:
    principal = get_current_principal(request)
    return principal.email if principal else "owner@summitflow.local"


def _comment_to_response(comment: dict[str, Any]) -> DesignAssetCommentResponse:
    return DesignAssetCommentResponse(**comment)


def _image_media_type(image_path: Path) -> str:
    """Return the response media type for a stored image asset."""
    return _IMAGE_MEDIA_TYPES.get(image_path.suffix.lower(), "image/png")


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
    sort_by: str = Query("created_desc"),
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
        sort_by=sort_by,
        voter_key="owner",
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
    asset = design_assets.get_asset(project_id, asset_id, voter_key="owner")
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
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Design asset file missing from durable storage")
    media_type = _image_media_type(image_path)
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
    "/projects/{project_id}/design-assets/import",
    response_model=GenerateDesignAssetResponse,
)
async def import_design_asset(
    project_id: str,
    request: ImportDesignAssetRequest,
) -> GenerateDesignAssetResponse:
    """Import a manually supplied image into Asset Studio for approval."""
    start_time = time.monotonic()
    try:
        asset = import_asset_image(
            project_id=project_id,
            name=request.name,
            image_base64=request.image_base64,
            mime_type=request.mime_type,
            original_file_name=request.original_file_name,
            prompt=request.prompt,
            description=request.description,
            asset_type=request.asset_type,
            workflow=request.workflow,
            background=request.background,
            transparent_background=request.transparent_background,
            source_asset_id=request.source_asset_id,
            sheet_columns=request.sheet_columns,
            sheet_rows=request.sheet_rows,
            frame_width=request.frame_width,
            frame_height=request.frame_height,
            animation_labels=request.animation_labels,
            tags=request.tags,
            metadata=request.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Asset import failed: {exc}") from exc

    generation_time_ms = int((time.monotonic() - start_time) * 1000)
    return GenerateDesignAssetResponse(
        success=True,
        assets=[asset_to_response(asset)],
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


@router.post(
    "/projects/{project_id}/design-assets/{asset_id}/rating",
    response_model=DesignAssetResponse,
)
async def rate_design_asset(
    project_id: str,
    asset_id: str,
    request: RateDesignAssetRequest,
) -> DesignAssetResponse:
    """Set or clear the owner's star rating for an asset."""
    try:
        asset = design_assets.set_asset_rating(
            project_id,
            asset_id,
            request.rating,
            voter_key="owner",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not asset:
        raise HTTPException(status_code=404, detail="Design asset not found")
    return asset_to_response(asset)


@router.get(
    "/projects/{project_id}/design-assets/{asset_id}/comments",
    response_model=list[DesignAssetCommentResponse],
)
async def list_design_asset_comments(
    project_id: str,
    asset_id: str,
) -> list[DesignAssetCommentResponse]:
    """List comments for an asset."""
    if not design_assets.get_asset(project_id, asset_id, voter_key="owner"):
        raise HTTPException(status_code=404, detail="Design asset not found")
    return [
        _comment_to_response(comment)
        for comment in design_assets.list_asset_comments(project_id, asset_id)
    ]


@router.post(
    "/projects/{project_id}/design-assets/{asset_id}/comments",
    response_model=DesignAssetCommentResponse,
    status_code=201,
)
async def create_design_asset_comment(
    project_id: str,
    asset_id: str,
    request: DesignAssetCommentRequest,
    http_request: Request,
) -> DesignAssetCommentResponse:
    """Create a comment for an asset."""
    try:
        comment = design_assets.create_asset_comment(
            project_id,
            asset_id,
            request.body,
            author_email=_comment_author(http_request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not comment:
        raise HTTPException(status_code=404, detail="Design asset not found")
    return _comment_to_response(comment)


@router.put(
    "/projects/{project_id}/design-assets/{asset_id}/comments/{comment_id}",
    response_model=DesignAssetCommentResponse,
)
async def update_design_asset_comment(
    project_id: str,
    asset_id: str,
    comment_id: int,
    request: DesignAssetCommentRequest,
    http_request: Request,
) -> DesignAssetCommentResponse:
    """Edit one of the current user's asset comments."""
    try:
        comment = design_assets.update_asset_comment(
            project_id,
            asset_id,
            comment_id,
            request.body,
            author_email=_comment_author(http_request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    return _comment_to_response(comment)


@router.delete("/projects/{project_id}/design-assets/{asset_id}/comments/{comment_id}")
async def delete_design_asset_comment(
    project_id: str,
    asset_id: str,
    comment_id: int,
    http_request: Request,
) -> dict[str, bool]:
    """Delete one of the current user's asset comments."""
    deleted = design_assets.delete_asset_comment(
        project_id,
        asset_id,
        comment_id,
        author_email=_comment_author(http_request),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Comment not found")
    return {"deleted": True}


@router.delete("/projects/{project_id}/design-assets/{asset_id}")
async def delete_design_asset(project_id: str, asset_id: str) -> dict[str, bool]:
    """Delete an asset and its exports."""
    deleted = design_assets.delete_asset(project_id, asset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Design asset not found")
    return {"deleted": True}
