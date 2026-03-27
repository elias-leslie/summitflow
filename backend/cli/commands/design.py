"""Design Ops commands for UI mockups and production assets."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..config import get_config
from ..output import handle_api_error, output_json, require_explicit_project

app = typer.Typer(help="Design Ops commands for UI design and asset studio")
asset_app = typer.Typer(help="Asset Studio generation and export commands")
ui_app = typer.Typer(help="UI Design mockup generation commands")

# ---------------------------------------------------------------------------
# Annotated type aliases — keeps command signatures readable and concise
# ---------------------------------------------------------------------------
_AssetType = Annotated[
    str,
    typer.Option(
        "--type", "-t",
        help="Asset type (sprite, sprite_sheet, portrait, environment, icon, illustration, ui_texture, marketing_mockup, tile_set, concept_art)",
    ),
]
_Workflow = Annotated[
    str,
    typer.Option("--workflow", "-w", help="Workflow lane: concept, production, marketing, ui"),
]
_Background = Annotated[
    str,
    typer.Option("--background", help="Background mode: transparent, solid, scene"),
]
_VariantCount = Annotated[
    int,
    typer.Option("--variants", min=1, max=4, help="Number of variants to generate"),
]


@app.callback(invoke_without_command=True)
def design_default(ctx: typer.Context) -> None:
    """Design Ops command group."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@asset_app.command("generate")
def generate_asset(
    name: Annotated[str, typer.Argument(help="Asset display name")],
    prompt: Annotated[str, typer.Argument(help="Creative brief for the generated asset")],
    description: Annotated[str | None, typer.Option("--description", "-d", help="Optional description stored with the asset")] = None,
    asset_type: _AssetType = "sprite",
    workflow: _Workflow = "concept",
    size: Annotated[str, typer.Option("--size", help="Target size in WIDTHxHEIGHT format")] = "1024x1024",
    model: Annotated[str | None, typer.Option("--model", help="Image model override")] = None,
    style_prompt: Annotated[str | None, typer.Option("--style", help="Style direction for the model prompt")] = None,
    negative_prompt: Annotated[str | None, typer.Option("--negative", help="Negative prompt guidance")] = None,
    background: _Background = "transparent",
    variant_count: _VariantCount = 1,
    tags: Annotated[str | None, typer.Option("--tags", help="Comma-separated tags")] = None,
    sheet_columns: Annotated[int | None, typer.Option("--sheet-columns", help="Sprite sheet columns")] = None,
    sheet_rows: Annotated[int | None, typer.Option("--sheet-rows", help="Sprite sheet rows")] = None,
    frame_width: Annotated[int | None, typer.Option("--frame-width", help="Sprite sheet frame width")] = None,
    frame_height: Annotated[int | None, typer.Option("--frame-height", help="Sprite sheet frame height")] = None,
    animation_labels: Annotated[str | None, typer.Option("--animations", help="Comma-separated animation row labels")] = None,
    source_asset_id: Annotated[int | None, typer.Option("--source-asset-id", help="Source asset DB id for variant derivation")] = None,
    reference_image_path: Annotated[str | None, typer.Option("--reference-image-path", help="Path to a PNG/JPEG/WebP reference image for sprite consistency")] = None,
    reference_mime_type: Annotated[str | None, typer.Option("--reference-mime-type", help="Reference image MIME type override")] = None,
) -> None:
    """Generate a Design Ops asset in Asset Studio for the active project.

    Requires explicit project: st -P <project> design asset generate ...
    """
    require_explicit_project(get_config())
    client = STClient()

    payload = _build_asset_payload(
        name=name, prompt=prompt, description=description,
        asset_type=asset_type, workflow=workflow, size=size,
        model=model, style_prompt=style_prompt, negative_prompt=negative_prompt,
        background=background, variant_count=variant_count, tags=tags,
        sheet_columns=sheet_columns, sheet_rows=sheet_rows,
        frame_width=frame_width, frame_height=frame_height,
        animation_labels=animation_labels, source_asset_id=source_asset_id,
        reference_image_path=reference_image_path, reference_mime_type=reference_mime_type,
    )

    try:
        result = client.post(client._url("/design-assets/generate"), json=payload)
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None

    output_json(result)


@asset_app.command("export")
def export_asset(
    asset_id: Annotated[str, typer.Argument(help="Design asset id to export")],
    export_type: Annotated[
        str,
        typer.Option("--type", "-t", help="Export type (currently: sprite-frames)"),
    ] = "sprite-frames",
) -> None:
    """Export an existing Design Ops asset.

    Currently supports sprite sheet frame exports.
    """
    require_explicit_project(get_config())
    client = STClient()

    export_path = _resolve_asset_export_path(asset_id, export_type)

    try:
        result = client.post(client._url(export_path))
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None

    output_json(result)


@ui_app.command("analyze")
def analyze_ui(
    page_url: Annotated[str, typer.Argument(help="Fully-qualified page URL to analyze")],
    page_path: Annotated[
        str | None,
        typer.Option("--page-path", help="Optional project page path metadata"),
    ] = None,
) -> None:
    """Generate a UI design review artifact for the active project."""
    require_explicit_project(get_config())
    client = STClient()

    try:
        result = client.post(
            client._url("/mockups/analyze-page"),
            json={"page_url": page_url, "page_path": page_path},
        )
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None

    output_json(result)


def _build_asset_payload(
    *,
    name: str,
    prompt: str,
    description: str | None,
    asset_type: str,
    workflow: str,
    size: str,
    model: str | None,
    style_prompt: str | None,
    negative_prompt: str | None,
    background: str,
    variant_count: int,
    tags: str | None,
    sheet_columns: int | None,
    sheet_rows: int | None,
    frame_width: int | None,
    frame_height: int | None,
    animation_labels: str | None,
    source_asset_id: int | None,
    reference_image_path: str | None = None,
    reference_mime_type: str | None = None,
) -> dict[str, Any]:
    """Build the asset generation payload."""
    payload: dict[str, Any] = {
        "name": name,
        "prompt": prompt,
        "asset_type": asset_type,
        "workflow": workflow,
        "size": size,
        "background": background,
        "transparent_background": background == "transparent",
        "variant_count": variant_count,
    }
    _apply_optional_fields(payload, description=description, model=model,
                           style_prompt=style_prompt, negative_prompt=negative_prompt,
                           source_asset_id=source_asset_id)
    _apply_reference_image(payload, reference_image_path, reference_mime_type)
    _apply_sheet_fields(payload, tags=tags, animation_labels=animation_labels,
                        sheet_columns=sheet_columns, sheet_rows=sheet_rows,
                        frame_width=frame_width, frame_height=frame_height)
    return payload


def _apply_optional_fields(
    payload: dict[str, Any],
    *,
    description: str | None,
    model: str | None,
    style_prompt: str | None,
    negative_prompt: str | None,
    source_asset_id: int | None,
) -> None:
    """Apply simple optional scalar fields to the payload in place."""
    if description:
        payload["description"] = description
    if model:
        payload["model"] = model
    if style_prompt:
        payload["style_prompt"] = style_prompt
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if source_asset_id is not None:
        payload["source_asset_id"] = source_asset_id


def _apply_reference_image(
    payload: dict[str, Any],
    reference_image_path: str | None,
    reference_mime_type: str | None,
) -> None:
    """Encode and attach a reference image to the payload in place."""
    if not reference_image_path:
        return
    image_path = Path(reference_image_path)
    payload["reference_image_path"] = str(image_path)
    payload["reference_image"] = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    payload["reference_mime_type"] = reference_mime_type or _guess_mime_type(image_path)


def _apply_sheet_fields(
    payload: dict[str, Any],
    *,
    tags: str | None,
    animation_labels: str | None,
    sheet_columns: int | None,
    sheet_rows: int | None,
    frame_width: int | None,
    frame_height: int | None,
) -> None:
    """Apply sprite sheet and tag fields to the payload in place."""
    parsed_tags = _split_csv(tags)
    if parsed_tags:
        payload["tags"] = parsed_tags
    parsed_animations = _split_csv(animation_labels)
    if parsed_animations:
        payload["animation_labels"] = parsed_animations
    if sheet_columns is not None:
        payload["sheet_columns"] = sheet_columns
    if sheet_rows is not None:
        payload["sheet_rows"] = sheet_rows
    if frame_width is not None:
        payload["frame_width"] = frame_width
    if frame_height is not None:
        payload["frame_height"] = frame_height


def _split_csv(value: str | None) -> list[str]:
    """Split a comma-separated option into trimmed values."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _guess_mime_type(path: Path) -> str:
    """Infer MIME type from a reference image file extension."""
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _resolve_asset_export_path(asset_id: str, export_type: str) -> str:
    """Map CLI export type to API path."""
    export_type_key = export_type.strip().lower()
    if export_type_key != "sprite-frames":
        raise typer.BadParameter("Unsupported export type. Use: sprite-frames")
    return f"/design-assets/{asset_id}/exports/sprite-frames"


app.add_typer(asset_app, name="asset")
app.add_typer(ui_app, name="ui")
