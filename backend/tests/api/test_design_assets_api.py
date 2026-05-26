"""API coverage for design asset workflows."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from PIL import Image


@patch("app.services.design_asset_pipeline.design_assets.create_asset")
@patch("app.services.design_asset_pipeline.get_sync_client")
def test_generate_design_asset_uses_project_scope(
    mock_get_client: MagicMock,
    mock_create_asset: MagicMock,
    client: Any,
    ensure_test_project: str,
) -> None:
    """Project id from the route should be forwarded to Agent Hub."""
    mock_client = MagicMock()
    mock_client.generate_image.return_value = SimpleNamespace(
        image_base64="aGVsbG8=",
        mime_type="image/png",
        model="served-image-model",
        provider="served-image-provider",
    )
    mock_get_client.return_value = mock_client
    mock_create_asset.return_value = {
        "id": 1,
        "project_id": ensure_test_project,
        "asset_id": "asset-123",
        "name": "Hero Sprite",
        "description": None,
        "asset_type": "sprite",
        "workflow": "concept",
        "status": "generated",
        "prompt": "prompt",
        "negative_prompt": None,
        "style_prompt": None,
        "background": "transparent",
        "width": 512,
        "height": 512,
        "transparent_background": True,
        "model": "served-image-model",
        "generator": "image-gen",
        "file_path": "/tmp/asset.png",
        "source_asset_id": None,
        "sheet_columns": None,
        "sheet_rows": None,
        "frame_width": None,
        "frame_height": None,
        "animation_labels": [],
        "tags": [],
        "metadata": {},
        "approved_at": None,
        "approved_by": None,
        "created_at": None,
        "updated_at": None,
    }

    response = client.post(
        f"/api/projects/{ensure_test_project}/design-assets/generate",
        json={
            "name": "Hero Sprite",
            "prompt": "Single sprite for main character",
            "asset_type": "sprite",
            "size": "512x512",
        },
    )

    assert response.status_code == 200
    mock_client.generate_image.assert_called_once()
    assert mock_client.generate_image.call_args.kwargs["project_id"] == ensure_test_project


def test_get_design_asset_image_serves_svg_media_type(
    client: Any,
    ensure_test_project: str,
    tmp_path: Path,
) -> None:
    """SVG design assets should be served with the browser-safe media type."""
    svg_path = tmp_path / "asset.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>',
        encoding="utf-8",
    )

    with (
        patch("app.api.design_assets.design_assets.get_asset") as mock_get_asset,
        patch("app.api.design_assets.validate_mockup_path", return_value=svg_path),
    ):
        mock_get_asset.return_value = {
            "asset_id": "asset-svg",
            "file_path": str(svg_path),
        }
        response = client.get(
            f"/api/projects/{ensure_test_project}/design-assets/asset-svg/image"
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")


def test_export_sprite_frames_creates_manifest(
    client: Any,
    ensure_test_project: str,
    tmp_path: Path,
) -> None:
    """Sprite sheet export endpoint slices frames and writes atlas metadata."""
    image_path = tmp_path / "sheet.png"
    image = Image.new("RGBA", (128, 64), (255, 0, 0, 255))
    image.save(image_path)

    with patch("app.api.design_assets.design_assets.get_asset") as mock_get_asset:
        mock_get_asset.return_value = {
            "id": 2,
            "project_id": ensure_test_project,
            "asset_id": "asset-sheet",
            "name": "Enemy Sheet",
            "description": None,
            "asset_type": "sprite_sheet",
            "workflow": "production",
            "status": "generated",
            "prompt": "sheet",
            "negative_prompt": None,
            "style_prompt": None,
            "background": "transparent",
            "width": 128,
            "height": 64,
            "transparent_background": True,
            "model": "served-image-model",
            "generator": "image-gen",
            "file_path": str(image_path),
            "source_asset_id": None,
            "sheet_columns": 2,
            "sheet_rows": 1,
            "frame_width": 64,
            "frame_height": 64,
            "animation_labels": ["idle"],
            "tags": [],
            "metadata": {},
            "approved_at": None,
            "approved_by": None,
            "created_at": None,
            "updated_at": None,
        }
        with patch("app.services.design_asset_pipeline.design_assets.create_asset_export") as mock_export:
            mock_export.side_effect = [
                {
                    "id": 1,
                    "asset_db_id": 2,
                    "export_id": "export-frames",
                    "export_type": "sprite_frames",
                    "file_path": str(tmp_path / "exports" / "frames"),
                    "manifest_path": str(tmp_path / "exports" / "atlas.json"),
                    "metadata": {"frame_count": 2},
                    "created_at": None,
                },
                {
                    "id": 2,
                    "asset_db_id": 2,
                    "export_id": "export-atlas",
                    "export_type": "atlas_json",
                    "file_path": str(tmp_path / "exports" / "atlas.json"),
                    "manifest_path": None,
                    "metadata": {"frame_count": 2},
                    "created_at": None,
                },
            ]
            response = client.post(
                f"/api/projects/{ensure_test_project}/design-assets/asset-sheet/exports/sprite-frames"
            )

    assert response.status_code == 200
    body = response.json()
    assert body["export_type"] == "sprite_frames"
    assert mock_export.call_count == 2


@patch("app.services.design_asset_pipeline.design_assets.create_asset")
@patch("app.services.design_asset_pipeline.get_sync_client")
def test_generate_design_asset_passes_reference_image_to_image_client(
    mock_get_client: MagicMock,
    mock_create_asset: MagicMock,
    client: Any,
    ensure_test_project: str,
) -> None:
    """Reference image fields should flow through the design asset pipeline."""
    mock_client = MagicMock()
    mock_client.generate_image.return_value = SimpleNamespace(
        image_base64="aGVsbG8=",
        mime_type="image/png",
        model="served-reference-image-model",
        provider="served-image-provider",
    )
    mock_get_client.return_value = mock_client
    mock_create_asset.return_value = {
        "id": 1,
        "project_id": ensure_test_project,
        "asset_id": "asset-123",
        "name": "Hero Sprite",
        "description": None,
        "asset_type": "sprite_sheet",
        "workflow": "production",
        "status": "generated",
        "prompt": "prompt",
        "negative_prompt": None,
        "style_prompt": None,
        "background": "transparent",
        "width": 512,
        "height": 512,
        "transparent_background": True,
        "model": "served-reference-image-model",
        "generator": "image-gen",
        "file_path": "/tmp/asset.png",
        "source_asset_id": None,
        "sheet_columns": 4,
        "sheet_rows": 2,
        "frame_width": 128,
        "frame_height": 128,
        "animation_labels": ["idle", "run"],
        "tags": [],
        "metadata": {},
        "approved_at": None,
        "approved_by": None,
        "created_at": None,
        "updated_at": None,
    }

    response = client.post(
        f"/api/projects/{ensure_test_project}/design-assets/generate",
        json={
            "name": "Hero Sprite",
            "prompt": "Single sprite for main character",
            "asset_type": "sprite_sheet",
            "size": "512x512",
            "agent_slug": "image-gen",
            "reference_image": "aGVsbG8=",
            "reference_mime_type": "image/png",
            "sheet_columns": 4,
            "sheet_rows": 2,
            "frame_width": 128,
            "frame_height": 128,
            "animation_labels": ["idle", "run"],
        },
    )

    assert response.status_code == 200
    kwargs = mock_client.generate_image.call_args.kwargs
    assert kwargs["agent_slug"] == "image-gen"
    assert kwargs["reference_image"] == "aGVsbG8="
    assert kwargs["reference_mime_type"] == "image/png"


@patch("app.services.design_asset_pipeline.design_assets.create_asset")
@patch("app.services.design_asset_pipeline.get_sync_client")
def test_generate_design_asset_returns_provider_failure_without_local_model_retry(
    mock_get_client: MagicMock,
    mock_create_asset: MagicMock,
    client: Any,
    ensure_test_project: str,
) -> None:
    """Provider fallback is owned by Agent Hub, not local project model lists."""
    mock_client = MagicMock()
    mock_client.generate_image.side_effect = RuntimeError("provider failed")
    mock_get_client.return_value = mock_client
    mock_create_asset.return_value = {
        "id": 1,
        "project_id": ensure_test_project,
        "asset_id": "asset-fallback",
        "name": "Hero Sprite",
        "description": None,
        "asset_type": "sprite_sheet",
        "workflow": "production",
        "status": "generated",
        "prompt": "prompt",
        "negative_prompt": None,
        "style_prompt": None,
        "background": "transparent",
        "width": 512,
        "height": 512,
        "transparent_background": True,
        "model": "served-image-model",
        "generator": "image-gen",
        "file_path": "/tmp/asset.png",
        "source_asset_id": None,
        "sheet_columns": 4,
        "sheet_rows": 2,
        "frame_width": 128,
        "frame_height": 128,
        "animation_labels": ["idle", "run"],
        "tags": [],
        "metadata": {
            "requested_agent": "image-gen",
            "served_model": "served-image-model",
            "served_provider": "served-image-provider",
        },
        "approved_at": None,
        "approved_by": None,
        "created_at": None,
        "updated_at": None,
    }

    response = client.post(
        f"/api/projects/{ensure_test_project}/design-assets/generate",
        json={
            "name": "Hero Sprite",
            "prompt": "Single sprite for main character",
            "asset_type": "sprite_sheet",
            "size": "512x512",
            "agent_slug": "image-gen",
            "sheet_columns": 4,
            "sheet_rows": 2,
            "frame_width": 128,
            "frame_height": 128,
            "animation_labels": ["idle", "run"],
        },
    )

    assert response.status_code == 502
    mock_client.generate_image.assert_called_once()
    assert mock_client.generate_image.call_args.kwargs["agent_slug"] == "image-gen"
