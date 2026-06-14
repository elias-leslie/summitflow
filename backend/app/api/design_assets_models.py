"""Pydantic models for design asset APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DesignAssetResponse(BaseModel):
    """Response model for a design asset."""

    id: int
    project_id: str
    asset_id: str
    name: str
    description: str | None
    asset_type: str
    workflow: str
    status: str
    prompt: str
    negative_prompt: str | None
    style_prompt: str | None
    background: str
    width: int
    height: int
    transparent_background: bool
    model: str | None
    generator: str | None
    file_path: str | None
    source_asset_id: int | None
    sheet_columns: int | None
    sheet_rows: int | None
    frame_width: int | None
    frame_height: int | None
    animation_labels: list[str]
    tags: list[str]
    metadata: dict[str, object]
    approved_at: str | None
    approved_by: str | None
    created_at: str | None
    updated_at: str | None


class DesignAssetListResponse(BaseModel):
    """List response for assets."""

    items: list[DesignAssetResponse]
    total: int
    limit: int
    offset: int


class DesignAssetStatsResponse(BaseModel):
    """Aggregated asset stats."""

    total: int
    by_status: dict[str, int]
    by_type: dict[str, int]
    unique_models: int


class DesignAssetExportResponse(BaseModel):
    """Export record for an asset."""

    id: int
    asset_db_id: int
    export_id: str
    export_type: str
    file_path: str
    manifest_path: str | None
    metadata: dict[str, object]
    created_at: str | None


class GenerateDesignAssetRequest(BaseModel):
    """Request payload for one or more generated assets."""

    name: str
    prompt: str
    description: str | None = None
    asset_type: str = "sprite"
    workflow: str = "concept"
    size: str = "1024x1024"
    agent_slug: str | None = None
    model: str | None = None
    style_prompt: str | None = None
    negative_prompt: str | None = None
    background: str = "transparent"
    transparent_background: bool = True
    variant_count: int = Field(default=1, ge=1, le=4)
    tags: list[str] = Field(default_factory=list)
    sheet_columns: int | None = Field(default=None, ge=1, le=16)
    sheet_rows: int | None = Field(default=None, ge=1, le=16)
    frame_width: int | None = Field(default=None, ge=1)
    frame_height: int | None = Field(default=None, ge=1)
    animation_labels: list[str] = Field(default_factory=list)
    source_asset_id: int | None = None
    reference_image: str | None = None
    reference_mime_type: str | None = "image/png"
    reference_image_path: str | None = None


class ImportDesignAssetRequest(BaseModel):
    """Request payload for a manually provided design asset image."""

    name: str
    image_base64: str
    mime_type: str
    original_file_name: str | None = None
    prompt: str = "Manual asset import"
    description: str | None = None
    asset_type: str = "sprite"
    workflow: str = "concept"
    background: str = "transparent"
    transparent_background: bool = True
    tags: list[str] = Field(default_factory=list)
    sheet_columns: int | None = Field(default=None, ge=1, le=16)
    sheet_rows: int | None = Field(default=None, ge=1, le=16)
    frame_width: int | None = Field(default=None, ge=1)
    frame_height: int | None = Field(default=None, ge=1)
    animation_labels: list[str] = Field(default_factory=list)
    source_asset_id: int | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class GenerateDesignAssetResponse(BaseModel):
    """Response for generated assets."""

    success: bool
    assets: list[DesignAssetResponse]
    generation_time_ms: int


class UpdateDesignAssetStatusRequest(BaseModel):
    """Request to update status."""

    status: str
    approved_by: str | None = None
