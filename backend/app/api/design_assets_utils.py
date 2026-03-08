"""Response helpers for design assets."""

from __future__ import annotations

from typing import Any

from .design_assets_models import DesignAssetExportResponse, DesignAssetResponse


def asset_to_response(asset: dict[str, Any]) -> DesignAssetResponse:
    """Convert asset storage payload to API response."""
    return DesignAssetResponse(**asset)


def export_to_response(export_row: dict[str, Any]) -> DesignAssetExportResponse:
    """Convert export storage payload to API response."""
    return DesignAssetExportResponse(**export_row)
