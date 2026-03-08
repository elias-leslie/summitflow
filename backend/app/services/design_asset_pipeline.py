"""Design asset generation and export workflow helpers."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from PIL import Image

from ..constants import GEMINI_IMAGE
from ..services.agent_hub_client import get_sync_client
from ..storage import design_assets
from .mockup_generator.storage_helpers import get_mockup_directory

VALID_IMAGE_MODELS = frozenset(
    {
        "gemini-3-pro-image-preview",
        "gemini-2.5-flash-image",
        "gemini-3.1-flash-image-preview",
        "nvidia/flux.1-kontext-dev",
        "nvidia/flux.1-dev",
    }
)
_MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


def parse_size(size: str) -> tuple[int, int]:
    """Parse WIDTHxHEIGHT input."""
    try:
        width_text, height_text = size.lower().split("x")
        return int(width_text), int(height_text)
    except (AttributeError, ValueError):
        return 1024, 1024


def normalize_asset_type(asset_type: str) -> str:
    """Map legacy names to the first-class asset type enum."""
    if asset_type == "sheet":
        return "sprite_sheet"
    if asset_type == "layout":
        return "marketing_mockup"
    if asset_type == "page":
        return "environment"
    return asset_type


def build_generation_prompt(
    *,
    asset_type: str,
    prompt: str,
    style_prompt: str | None,
    negative_prompt: str | None,
    background: str,
    width: int,
    height: int,
    transparent_background: bool,
    sheet_columns: int | None,
    sheet_rows: int | None,
    frame_width: int | None,
    frame_height: int | None,
    animation_labels: list[str] | None,
) -> str:
    """Build the final image prompt."""
    parts = [f"Create a polished {asset_type.replace('_', ' ')} for a game production pipeline."]
    parts.append(f"Primary brief: {prompt}")
    parts.append(f"Target resolution: {width}x{height}px.")
    if transparent_background:
        parts.append("Use a transparent background.")
    else:
        parts.append(f"Background mode: {background}.")
    if style_prompt:
        parts.append(f"Style direction: {style_prompt}.")
    if asset_type == "sprite_sheet":
        cols = sheet_columns or 4
        rows = sheet_rows or 2
        parts.append(f"Sprite sheet layout: {cols} columns by {rows} rows.")
        if frame_width and frame_height:
            parts.append(f"Each frame should fit {frame_width}x{frame_height}px.")
        if animation_labels:
            parts.append(f"Animation rows: {', '.join(animation_labels)}.")
        parts.append("Keep framing consistent across every cell and leave visible separation lines.")
    elif asset_type in {"sprite", "icon", "ui_texture", "portrait"}:
        parts.append("Keep edges clean and suitable for compositing.")
    elif asset_type in {"environment", "concept_art", "marketing_mockup"}:
        parts.append("Compose with strong readability and production-ready lighting.")
    if negative_prompt:
        parts.append(f"Avoid: {negative_prompt}.")
    return "\n".join(parts)


def _resolve_model(model: str | None) -> str:
    """Resolve a requested image model."""
    if model and model in VALID_IMAGE_MODELS:
        return model
    return GEMINI_IMAGE


def generate_asset_image(
    *,
    project_id: str,
    asset_type: str,
    workflow: str,
    name: str,
    description: str | None,
    prompt: str,
    style_prompt: str | None,
    negative_prompt: str | None,
    background: str,
    transparent_background: bool,
    size: str,
    model: str | None,
    generator: str = "gemini-image",
    source_asset_id: int | None = None,
    sheet_columns: int | None = None,
    sheet_rows: int | None = None,
    frame_width: int | None = None,
    frame_height: int | None = None,
    animation_labels: list[str] | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    reference_image: str | None = None,
    reference_mime_type: str | None = None,
) -> dict[str, Any]:
    """Generate an image and persist a design asset."""
    normalized_type = normalize_asset_type(asset_type)
    width, height = parse_size(size)
    merged_prompt = build_generation_prompt(
        asset_type=normalized_type,
        prompt=prompt,
        style_prompt=style_prompt,
        negative_prompt=negative_prompt,
        background=background,
        width=width,
        height=height,
        transparent_background=transparent_background,
        sheet_columns=sheet_columns,
        sheet_rows=sheet_rows,
        frame_width=frame_width,
        frame_height=frame_height,
        animation_labels=animation_labels,
    )
    resolved_model = _resolve_model(model)
    client = get_sync_client()
    response = client.generate_image(
        prompt=merged_prompt,
        project_id=project_id,
        purpose="design_asset_generation",
        model=resolved_model,
        size=f"{width}x{height}",
        style=style_prompt,
        reference_image=reference_image,
        reference_mime_type=reference_mime_type,
    )
    image_bytes = base64.b64decode(response.image_base64)
    ext = _MIME_TO_EXT.get(response.mime_type, "png")

    asset_id = design_assets.generate_asset_id()
    asset_dir = get_mockup_directory(project_id, asset_id)
    asset_dir.mkdir(parents=True, exist_ok=True)
    image_path = asset_dir / f"asset.{ext}"
    image_path.write_bytes(image_bytes)

    return design_assets.create_asset(
        project_id=project_id,
        asset_id=asset_id,
        name=name,
        description=description,
        asset_type=normalized_type,
        workflow=workflow,
        prompt=merged_prompt,
        negative_prompt=negative_prompt,
        style_prompt=style_prompt,
        background=background,
        width=width,
        height=height,
        transparent_background=transparent_background,
        model=resolved_model,
        generator=generator,
        file_path=str(image_path),
        source_asset_id=source_asset_id,
        sheet_columns=sheet_columns,
        sheet_rows=sheet_rows,
        frame_width=frame_width,
        frame_height=frame_height,
        animation_labels=animation_labels,
        tags=tags,
        metadata=metadata,
    )


def export_sprite_sheet_frames(asset: dict[str, Any]) -> dict[str, Any]:
    """Slice a sprite sheet into frame exports plus a JSON atlas manifest."""
    file_path = asset.get("file_path")
    if not file_path:
        raise ValueError("Asset has no file to export")
    if asset["asset_type"] != "sprite_sheet":
        raise ValueError("Only sprite sheet assets support frame exports")

    image_path = Path(file_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Asset image not found: {image_path}")

    frame_width = asset.get("frame_width")
    frame_height = asset.get("frame_height")
    sheet_columns = asset.get("sheet_columns")
    sheet_rows = asset.get("sheet_rows")
    if not all([frame_width, frame_height, sheet_columns, sheet_rows]):
        raise ValueError("Sprite sheet export requires frame dimensions and grid metadata")
    frame_width = int(frame_width)
    frame_height = int(frame_height)
    sheet_columns = int(sheet_columns)
    sheet_rows = int(sheet_rows)

    export_dir = image_path.parent / "exports" / "frames"
    export_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = image_path.parent / "exports" / "atlas.json"
    atlas_frames: dict[str, Any] = {}

    with Image.open(image_path) as image:
        for row in range(sheet_rows):
            for col in range(sheet_columns):
                left = col * frame_width
                top = row * frame_height
                right = left + frame_width
                bottom = top + frame_height
                frame = image.crop((left, top, right, bottom))
                animation = (
                    asset["animation_labels"][row]
                    if row < len(asset["animation_labels"])
                    else f"row-{row + 1}"
                )
                frame_name = f"{animation}_{col + 1:02d}.png"
                frame_path = export_dir / frame_name
                frame.save(frame_path)
                atlas_frames[frame_name] = {
                    "frame": {"x": left, "y": top, "w": frame_width, "h": frame_height},
                    "sourceSize": {"w": frame_width, "h": frame_height},
                }

    manifest = {
        "frames": atlas_frames,
        "meta": {
            "app": "summitflow",
            "asset_id": asset["asset_id"],
            "size": {"w": asset["width"], "h": asset["height"]},
            "frame_size": {"w": frame_width, "h": frame_height},
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    export_record = design_assets.create_asset_export(
        asset["id"],
        "sprite_frames",
        str(export_dir),
        manifest_path=str(manifest_path),
        metadata={
            "frame_count": sheet_columns * sheet_rows,
            "frame_width": frame_width,
            "frame_height": frame_height,
        },
    )
    design_assets.create_asset_export(
        asset["id"],
        "atlas_json",
        str(manifest_path),
        metadata={"frame_count": sheet_columns * sheet_rows},
    )
    return export_record
