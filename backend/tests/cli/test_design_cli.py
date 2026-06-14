"""Tests for Design Ops CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.commands.design import _build_asset_payload, _build_import_asset_payload
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
        agent_slug="image-gen",
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
    assert payload["transparent_background"]


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


def test_build_import_asset_payload_encodes_svg_and_metadata(tmp_path: Path) -> None:
    """Manual asset imports should encode the image and mark the source gate."""
    image_path = tmp_path / "icon.svg"
    image_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"></svg>',
        encoding="utf-8",
    )

    payload = _build_import_asset_payload(
        name="AfterTimes Icon",
        image_file=image_path,
        prompt="Manual SVG icon candidate",
        description="Review candidate",
        asset_type="icon",
        workflow="concept",
        background="transparent",
        tags="aftertimes, icon",
        sheet_columns=None,
        sheet_rows=None,
        frame_width=None,
        frame_height=None,
        animation_labels=None,
        source_asset_id=None,
        generator_note="codex",
    )

    assert payload["mime_type"] == "image/svg+xml"
    assert payload["image_base64"]
    assert payload["original_file_name"] == "icon.svg"
    assert payload["metadata"] == {
        "source_gate": "manual-current-agent",
        "generator_note": "codex",
    }
    assert payload["tags"] == ["aftertimes", "icon"]


def test_design_asset_import_posts_to_design_assets_endpoint(tmp_path: Path) -> None:
    """CLI should post manual import payload to the design-assets import endpoint."""
    image_path = tmp_path / "scout.svg"
    image_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"></svg>',
        encoding="utf-8",
    )
    mock_client = MagicMock()
    mock_client._url.side_effect = lambda path: f"http://localhost:8001/api/projects/the-aftertimes{path}"
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
                "the-aftertimes",
                "design",
                "asset",
                "import",
                "Scout Sprite",
                str(image_path),
                "--type",
                "sprite",
                "--workflow",
                "concept",
                "--tags",
                "scout,manual",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_client.post.assert_called_once()
    called_url = mock_client.post.call_args.args[0]
    called_json = mock_client.post.call_args.kwargs["json"]
    assert called_url.endswith("/design-assets/import")
    assert called_json["asset_type"] == "sprite"
    assert called_json["mime_type"] == "image/svg+xml"
    assert called_json["tags"] == ["scout", "manual"]


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
        agent_slug="image-gen",
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


def test_design_ui_create_posts_manual_html_to_mockups_endpoint(tmp_path: Path) -> None:
    """`ui create` should POST hand-authored HTML to the mockups endpoint with generator=manual-html."""
    html_path = tmp_path / "layout-a.html"
    html_path.write_text("<section>layout a</section>", encoding="utf-8")

    mock_client = MagicMock()
    mock_client._url.side_effect = lambda path: f"http://localhost:8001/api/projects/summitflow{path}"
    mock_client.post.return_value = {"success": True, "mockup_id": "mk-new"}

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
                "create",
                "today-layout-a",
                "--html-file",
                str(html_path),
                "--description",
                "Balanced layout",
                "--mockup-type",
                "page",
                "--reference-url",
                "https://portfolio.example.com/",
                "--reference-image",
                "/tmp/today.png",
                "--tags",
                "signals,deterministic",
                "--task-id",
                "task-123",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_client.post.assert_called_once()
    called_url = mock_client.post.call_args.args[0]
    called_json = mock_client.post.call_args.kwargs["json"]
    assert called_url.endswith("/mockups")
    assert called_json["name"] == "today-layout-a"
    assert called_json["content"] == "<section>layout a</section>"
    assert called_json["generator"] == "manual-html"
    assert called_json["mockup_type"] == "page"
    assert called_json["page_path"] == "https://portfolio.example.com/"
    assert called_json["task_id"] == "task-123"
    assert called_json["description"] == "Balanced layout"
    assert called_json["metadata"]["reference_image_path"] == "/tmp/today.png"
    assert called_json["metadata"]["tags"] == ["signals", "deterministic"]
    assert "parent_mockup_id" not in called_json


def test_design_ui_create_rejects_empty_html(tmp_path: Path) -> None:
    """`ui create` should fail when no HTML content is provided."""
    mock_client = MagicMock()
    with (
        patch("cli.commands.design.require_explicit_project"),
        patch("cli.commands.design.get_config"),
        patch("cli.commands.design.STClient", return_value=mock_client),
    ):
        result = runner.invoke(
            app,
            ["-P", "summitflow", "design", "ui", "create", "missing-html"],
        )
    assert result.exit_code != 0
    mock_client.post.assert_not_called()


def test_design_ui_attach_resolves_parent_id_and_posts_revision(tmp_path: Path) -> None:
    """`ui attach` should GET the parent mockup, then POST a child mockup with parent_mockup_id."""
    html_path = tmp_path / "layout-a-v2.html"
    html_path.write_text("<section>v2</section>", encoding="utf-8")

    mock_client = MagicMock()
    mock_client._url.side_effect = lambda path: f"http://localhost:8001/api/projects/summitflow{path}"
    mock_client.get.return_value = {
        "id": 42,
        "mockup_id": "mk-parent",
        "name": "today-layout-a",
        "mockup_type": "page",
        "page_path": "https://portfolio.example.com/",
        "task_id": "task-123",
    }
    mock_client.post.return_value = {"success": True, "mockup_id": "mk-child"}

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
                "attach",
                "mk-parent",
                "--html-file",
                str(html_path),
                "-d",
                "v2 tightened spacing",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_client.get.assert_called_once()
    called_get_url = mock_client.get.call_args.args[0]
    assert called_get_url.endswith("/mockups/mk-parent")

    mock_client.post.assert_called_once()
    called_post_url = mock_client.post.call_args.args[0]
    called_json = mock_client.post.call_args.kwargs["json"]
    assert called_post_url.endswith("/mockups")
    assert called_json["parent_mockup_id"] == 42
    assert called_json["name"] == "today-layout-a"
    assert called_json["content"] == "<section>v2</section>"
    assert called_json["generator"] == "manual-html"
    assert called_json["mockup_type"] == "page"
    assert called_json["page_path"] == "https://portfolio.example.com/"
    assert called_json["task_id"] == "task-123"
    assert called_json["description"] == "v2 tightened spacing"


def test_design_ui_rerun_posts_notes_to_mockup_endpoint() -> None:
    """CLI should route mockup reruns to the project mockup revision endpoint."""
    mock_client = MagicMock()
    mock_client._url.side_effect = lambda path: f"http://localhost:8001/api/projects/summitflow{path}"
    mock_client.post.return_value = {"success": True, "mockup": {"mockup_id": "mk-child"}}

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
                "rerun",
                "mk-parent",
                "--notes",
                "Tighten spacing and keep current color palette",
            ],
        )

    assert result.exit_code == 0
    mock_client.post.assert_called_once()
    called_url = mock_client.post.call_args.args[0]
    called_json = mock_client.post.call_args.kwargs["json"]
    assert called_url.endswith("/mockups/mk-parent/rerun")
    assert called_json["notes"] == "Tighten spacing and keep current color palette"
