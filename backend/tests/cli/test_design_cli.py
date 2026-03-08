"""Tests for Design Ops CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.commands.design import _build_asset_payload
from cli.main import app

runner = CliRunner()


def test_build_asset_payload_parses_csv_options() -> None:
    """CSV options should become trimmed lists in the payload."""
    payload = _build_asset_payload(
        name="Hero Sheet",
        prompt="Main fighter combo sheet",
        description="Production sprite sheet",
        asset_type="sprite_sheet",
        workflow="production",
        size="1024x1024",
        model="gemini-3-pro-image-preview",
        style_prompt="bold outlines",
        negative_prompt="watermark, blurry",
        background="transparent",
        variant_count=2,
        tags="hero, combat , player",
        sheet_columns=4,
        sheet_rows=2,
        frame_width=128,
        frame_height=128,
        animation_labels="idle, attack",
        source_asset_id=42,
    )

    assert payload["tags"] == ["hero", "combat", "player"]
    assert payload["animation_labels"] == ["idle", "attack"]
    assert payload["transparent_background"] is True


def test_design_asset_generate_posts_to_design_assets_endpoint() -> None:
    """CLI should post asset generation payload to the design-assets endpoint."""
    mock_client = MagicMock()
    mock_client._url.side_effect = lambda path: f"http://localhost:8001/api/projects/monkey-fight{path}"
    mock_client.post.return_value = {"success": True, "assets": [{"asset_id": "asset-1"}]}

    with (
        patch("cli.commands.design.require_explicit_project"),
        patch("cli.commands.design.get_config"),
        patch("cli.commands.design.STClient", return_value=mock_client),
    ):
        result = runner.invoke(
            app,
            [
                "-P",
                "monkey-fight",
                "design",
                "asset",
                "generate",
                "Kiki attack sheet",
                "Capuchin fighter combo sheet",
                "--type",
                "sprite_sheet",
                "--workflow",
                "production",
                "--variants",
                "2",
                "--sheet-columns",
                "4",
                "--sheet-rows",
                "2",
                "--frame-width",
                "128",
                "--frame-height",
                "128",
                "--animations",
                "idle,attack",
                "--tags",
                "kiki,combat",
            ],
        )

    assert result.exit_code == 0
    mock_client.post.assert_called_once()
    called_url = mock_client.post.call_args.args[0]
    called_json = mock_client.post.call_args.kwargs["json"]
    assert called_url.endswith("/design-assets/generate")
    assert called_json["asset_type"] == "sprite_sheet"
    assert called_json["tags"] == ["kiki", "combat"]


def test_build_asset_payload_includes_reference_image_options(tmp_path: Path) -> None:
    """Reference image options should be passed through to the API payload."""
    ref_path = tmp_path / "coco-ref.png"
    ref_path.write_bytes(b"ref-image")

    payload = _build_asset_payload(
        name="Coco Reference Sheet",
        prompt="Gorilla fighter turnaround",
        description=None,
        asset_type="sprite_sheet",
        workflow="production",
        size="1024x1024",
        model="nvidia/flux.1-kontext-dev",
        style_prompt="pixel art",
        negative_prompt=None,
        background="transparent",
        variant_count=1,
        tags=None,
        sheet_columns=4,
        sheet_rows=2,
        frame_width=128,
        frame_height=128,
        animation_labels="idle,run",
        source_asset_id=None,
        reference_image_path=str(ref_path),
        reference_mime_type="image/png",
    )

    assert payload["reference_image_path"] == str(ref_path)
    assert payload["reference_image"] == "cmVmLWltYWdl"
    assert payload["reference_mime_type"] == "image/png"


def test_design_ui_analyze_posts_to_mockups_endpoint() -> None:
    """CLI should route UI analysis to the project mockups endpoint."""
    mock_client = MagicMock()
    mock_client._url.side_effect = lambda path: f"http://localhost:8001/api/projects/summitflow{path}"
    mock_client.post.return_value = {"success": True, "mockup_id": "mk-123"}

    with (
        patch("cli.commands.design.require_explicit_project"),
        patch("cli.commands.design.get_config"),
        patch("cli.commands.design.STClient", return_value=mock_client),
    ):
        result = runner.invoke(
            app,
            [
                "-P",
                "summitflow",
                "design",
                "ui",
                "analyze",
                "http://localhost:3001/projects/summitflow",
                "--page-path",
                "/projects/summitflow",
            ],
        )

    assert result.exit_code == 0
    mock_client.post.assert_called_once()
    called_url = mock_client.post.call_args.args[0]
    called_json = mock_client.post.call_args.kwargs["json"]
    assert called_url.endswith("/mockups/analyze-page")
    assert called_json["page_path"] == "/projects/summitflow"
