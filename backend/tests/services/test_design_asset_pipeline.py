"""Tests for design asset pipeline helpers."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.design_asset_pipeline import import_asset_image


@patch("app.services.design_asset_pipeline.design_assets.create_asset")
@patch("app.services.design_asset_pipeline.design_assets.generate_asset_id")
def test_import_asset_image_persists_svg_without_agent_hub(
    mock_generate_asset_id: MagicMock,
    mock_create_asset: MagicMock,
    tmp_path: Path,
) -> None:
    """Manual SVG imports should store bytes and metadata without Agent Hub."""
    mock_generate_asset_id.return_value = "asset-manual"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="16">'
        "<rect width='32' height='16'/></svg>"
    )
    with patch(
        "app.services.design_asset_pipeline.get_mockup_directory",
        return_value=tmp_path / "asset-manual",
    ):
        import_asset_image(
            project_id="the-aftertimes",
            name="Manual Icon",
            image_base64=base64.b64encode(svg.encode()).decode(),
            mime_type="image/svg+xml",
            original_file_name="icon.svg",
            prompt="Manual import",
            description=None,
            asset_type="icon",
            workflow="concept",
            background="transparent",
            transparent_background=True,
            tags=["manual"],
            metadata={"source_gate": "manual-current-agent"},
        )

    image_path = tmp_path / "asset-manual" / "asset.svg"
    assert image_path.read_text(encoding="utf-8") == svg
    kwargs = mock_create_asset.call_args.kwargs
    assert kwargs["project_id"] == "the-aftertimes"
    assert kwargs["asset_id"] == "asset-manual"
    assert kwargs["width"] == 32
    assert kwargs["height"] == 16
    assert kwargs["model"] == "manual"
    assert kwargs["generator"] == "manual-image"
    assert kwargs["metadata"] == {
        "source_gate": "manual-current-agent",
        "source": "manual-import",
        "mime_type": "image/svg+xml",
        "original_file_name": "icon.svg",
    }


def test_import_asset_image_rejects_active_svg(tmp_path: Path) -> None:
    """Manual SVG imports should reject active content before persistence."""
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script /></svg>'
    with (
        patch("app.services.design_asset_pipeline.get_mockup_directory", return_value=tmp_path),
        patch("app.services.design_asset_pipeline.design_assets.create_asset") as mock_create_asset,
        pytest.raises(ValueError, match="unsupported active content"),
    ):
        import_asset_image(
            project_id="the-aftertimes",
            name="Unsafe SVG",
            image_base64=base64.b64encode(svg.encode()).decode(),
            mime_type="image/svg+xml",
            original_file_name="unsafe.svg",
            prompt="Manual import",
            description=None,
            asset_type="icon",
            workflow="concept",
            background="transparent",
            transparent_background=True,
        )

    mock_create_asset.assert_not_called()


def test_import_asset_image_rejects_svg_entity_expansion(tmp_path: Path) -> None:
    """Untrusted SVG must not resolve internal entities."""
    svg = """<!DOCTYPE svg [<!ENTITY payload "expanded">]>
    <svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">
      <text>&payload;</text>
    </svg>"""
    with (
        patch("app.services.design_asset_pipeline.get_mockup_directory", return_value=tmp_path),
        patch("app.services.design_asset_pipeline.design_assets.create_asset") as mock_create_asset,
        pytest.raises(ValueError, match="Invalid SVG asset"),
    ):
        import_asset_image(
            project_id="the-aftertimes",
            name="Entity SVG",
            image_base64=base64.b64encode(svg.encode()).decode(),
            mime_type="image/svg+xml",
            original_file_name="entity.svg",
            prompt="Manual import",
            description=None,
            asset_type="icon",
            workflow="concept",
            background="transparent",
            transparent_background=True,
        )

    mock_create_asset.assert_not_called()
