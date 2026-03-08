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
        model="gemini-3-pro-image-preview",
        provider="gemini",
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
        "model": "gemini-3-pro-image-preview",
        "generator": "gemini-image",
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
            "model": "gemini-3-pro-image-preview",
            "generator": "gemini-image",
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
        model="nvidia/flux.1-kontext-dev",
        provider="nvidia",
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
        "model": "nvidia/flux.1-kontext-dev",
        "generator": "gemini-image",
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
            "model": "nvidia/flux.1-kontext-dev",
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
    assert kwargs["model"] == "nvidia/flux.1-kontext-dev"
    assert kwargs["reference_image"] == "aGVsbG8="
    assert kwargs["reference_mime_type"] == "image/png"


@patch("app.services.design_asset_pipeline.design_assets.create_asset")
@patch("app.services.design_asset_pipeline.get_sync_client")
def test_generate_design_asset_falls_back_to_next_model_on_provider_failure(
    mock_get_client: MagicMock,
    mock_create_asset: MagicMock,
    client: Any,
    ensure_test_project: str,
) -> None:
    """Sprite sheet generation should continue through the fallback chain."""
    mock_client = MagicMock()
    mock_client.generate_image.side_effect = [
        RuntimeError("nvidia failed"),
        SimpleNamespace(
            image_base64="aGVsbG8=",
            mime_type="image/png",
            model="cloudflare/flux-2-dev",
            provider="cloudflare",
        ),
    ]
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
        "model": "cloudflare/flux-2-dev",
        "generator": "gemini-image",
        "file_path": "/tmp/asset.png",
        "source_asset_id": None,
        "sheet_columns": 4,
        "sheet_rows": 2,
        "frame_width": 128,
        "frame_height": 128,
        "animation_labels": ["idle", "run"],
        "tags": [],
        "metadata": {
            "requested_model": "nvidia/flux.1-kontext-dev",
            "served_model": "cloudflare/flux-2-dev",
            "served_provider": "cloudflare",
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
            "model": "nvidia/flux.1-kontext-dev",
            "sheet_columns": 4,
            "sheet_rows": 2,
            "frame_width": 128,
            "frame_height": 128,
            "animation_labels": ["idle", "run"],
        },
    )

    assert response.status_code == 200
    assert mock_client.generate_image.call_count == 2
    first_call = mock_client.generate_image.call_args_list[0].kwargs
    second_call = mock_client.generate_image.call_args_list[1].kwargs
    assert first_call["model"] == "nvidia/flux.1-kontext-dev"
    assert second_call["model"] == "cloudflare/flux-2-dev"
