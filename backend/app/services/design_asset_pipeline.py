"""Design asset generation and export workflow helpers."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from PIL import Image

from ..constants import GEMINI_IMAGE
from ..services.agent_hub_client import get_sync_client
from ..storage import design_assets
from .mockup_generator.storage_helpers import get_mockup_directory

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_IMAGE_MODELS = frozenset(
    {
        "gemini-3-pro-image-preview",
        "gemini-2.5-flash-image",
        "gemini-3.1-flash-image-preview",
        "nvidia/flux.1-kontext-dev",
        "nvidia/flux.1-dev",
        "nvidia/flux.1-schnell",
        "cloudflare/flux-2-dev",
        "cloudflare/flux-1-schnell",
        "cloudflare/sd-xl-lightning",
    }
)

_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/webp": "webp",
}

_SPRITE_FALLBACK_MODELS: tuple[str, ...] = (
    "cloudflare/flux-2-dev",
    "cloudflare/flux-1-schnell",
    "nvidia/flux.1-dev",
    "nvidia/flux.1-schnell",
    "gemini-3.1-flash-image-preview",
    "gemini-2.5-flash-image",
)

_GENERIC_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-3.1-flash-image-preview",
    "gemini-2.5-flash-image",
)

_BACKGROUND_TRANSPARENT = "transparent"
_PURPOSE_DESIGN_ASSET = "design_asset_generation"
_META_APP = "summitflow"

# Asset type groups
_COMPOSITE_ASSET_TYPES = frozenset({"sprite", "icon", "ui_texture", "portrait"})
_SCENE_ASSET_TYPES = frozenset({"environment", "concept_art", "marketing_mockup"})


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def parse_size(size: str) -> tuple[int, int]:
    """Parse WIDTHxHEIGHT input."""
    try:
        width_text, height_text = size.lower().split("x")
        return int(width_text), int(height_text)
    except (AttributeError, ValueError):
        return 1024, 1024


def normalize_asset_type(asset_type: str) -> str:
    """Map legacy names to the first-class asset type enum."""
    _legacy: dict[str, str] = {
        "sheet": "sprite_sheet",
        "layout": "marketing_mockup",
        "page": "environment",
    }
    return _legacy.get(asset_type, asset_type)


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
    _append_asset_type_guidance(parts, asset_type, sheet_columns, sheet_rows, frame_width, frame_height, animation_labels)
    if negative_prompt:
        parts.append(f"Avoid: {negative_prompt}.")
    return "\n".join(parts)


def _append_asset_type_guidance(
    parts: list[str],
    asset_type: str,
    sheet_columns: int | None,
    sheet_rows: int | None,
    frame_width: int | None,
    frame_height: int | None,
    animation_labels: list[str] | None,
) -> None:
    """Append asset-type-specific guidance lines to the prompt parts list."""
    if asset_type == "sprite_sheet":
        cols = sheet_columns or 4
        rows = sheet_rows or 2
        parts.append(f"Sprite sheet layout: {cols} columns by {rows} rows.")
        if frame_width and frame_height:
            parts.append(f"Each frame should fit {frame_width}x{frame_height}px.")
        if animation_labels:
            parts.append(f"Animation rows: {', '.join(animation_labels)}.")
        parts.append("Keep framing consistent across every cell and leave visible separation lines.")
    elif asset_type in _COMPOSITE_ASSET_TYPES:
        parts.append("Keep edges clean and suitable for compositing.")
    elif asset_type in _SCENE_ASSET_TYPES:
        parts.append("Compose with strong readability and production-ready lighting.")


# ---------------------------------------------------------------------------
# Model resolution helpers
# ---------------------------------------------------------------------------


def _resolve_model(model: str | None) -> str:
    """Resolve a requested image model, falling back to the default."""
    if model and model in VALID_IMAGE_MODELS:
        return model
    return GEMINI_IMAGE


def _candidate_models(
    requested_model: str,
    *,
    asset_type: str,
    reference_image: str | None,
) -> list[str]:
    """Build an ordered image-model chain for this asset generation."""
    fallbacks = _SPRITE_FALLBACK_MODELS if (asset_type == "sprite_sheet" or reference_image) else _GENERIC_FALLBACK_MODELS
    seen: set[str] = set()
    ordered: list[str] = []
    for model_id in (requested_model, *fallbacks):
        if model_id in seen:
            continue
        seen.add(model_id)
        ordered.append(model_id)
    return ordered


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------


def _call_image_api(
    *,
    client: object,
    candidates: list[str],
    prompt: str,
    project_id: str,
    width: int,
    height: int,
    style_prompt: str | None,
    reference_image: str | None,
    reference_mime_type: str | None,
) -> object:
    """Try each candidate model in order; return the first successful response."""
    last_error: Exception | None = None
    for try_model in candidates:
        try:
            return client.generate_image(  # type: ignore[union-attr]
                prompt=prompt,
                project_id=project_id,
                purpose=_PURPOSE_DESIGN_ASSET,
                model=try_model,
                size=f"{width}x{height}",
                style=style_prompt,
                reference_image=reference_image,
                reference_mime_type=reference_mime_type,
            )
        except Exception as exc:
            last_error = exc
    raise last_error or RuntimeError("Asset generation failed without a provider response")


def _save_image_file(project_id: str, asset_id: str, image_bytes: bytes, ext: str) -> Path:
    """Write image bytes to disk and return the path."""
    asset_dir = get_mockup_directory(project_id, asset_id)
    asset_dir.mkdir(parents=True, exist_ok=True)
    image_path = asset_dir / f"asset.{ext}"
    image_path.write_bytes(image_bytes)
    return image_path


def _persist_asset(
    project_id: str,
    asset_id: str,
    image_path: Path,
    *,
    name: str,
    description: str | None,
    normalized_type: str,
    workflow: str,
    merged_prompt: str,
    negative_prompt: str | None,
    style_prompt: str | None,
    background: str,
    width: int,
    height: int,
    transparent_background: bool,
    served_model: str,
    generator: str,
    source_asset_id: int | None,
    sheet_columns: int | None,
    sheet_rows: int | None,
    frame_width: int | None,
    frame_height: int | None,
    animation_labels: list[str] | None,
    tags: list[str] | None,
    extra_metadata: dict[str, str | int],
) -> dict[str, object]:
    """Write asset record to the database and return it."""
    return design_assets.create_asset(
        project_id=project_id, asset_id=asset_id, name=name,
        description=description, asset_type=normalized_type, workflow=workflow,
        prompt=merged_prompt, negative_prompt=negative_prompt,
        style_prompt=style_prompt, background=background, width=width, height=height,
        transparent_background=transparent_background, model=served_model,
        generator=generator, file_path=str(image_path),
        source_asset_id=source_asset_id, sheet_columns=sheet_columns,
        sheet_rows=sheet_rows, frame_width=frame_width, frame_height=frame_height,
        animation_labels=animation_labels, tags=tags, metadata=extra_metadata,
    )


def _generate_and_save(
    *,
    project_id: str,
    normalized_type: str,
    merged_prompt: str,
    style_prompt: str | None,
    reference_image: str | None,
    reference_mime_type: str | None,
    width: int,
    height: int,
    resolved_model: str,
) -> tuple[str, Path, object]:
    """Call the image API and write the result to disk; return (asset_id, image_path, response)."""
    candidates = _candidate_models(resolved_model, asset_type=normalized_type, reference_image=reference_image)
    response = _call_image_api(
        client=get_sync_client(), candidates=candidates, prompt=merged_prompt,
        project_id=project_id, width=width, height=height, style_prompt=style_prompt,
        reference_image=reference_image, reference_mime_type=reference_mime_type,
    )
    image_bytes = base64.b64decode(response.image_base64)  # type: ignore[union-attr]
    ext = _MIME_TO_EXT.get(response.mime_type, "png")  # type: ignore[union-attr]
    asset_id = design_assets.generate_asset_id()
    return asset_id, _save_image_file(project_id, asset_id, image_bytes, ext), response


def _make_served_metadata(
    base: dict[str, str | int] | None, resolved_model: str, response: object,
) -> dict[str, str | int]:
    """Merge caller metadata with provider telemetry fields."""
    return {
        **(base or {}),
        "requested_model": resolved_model,
        "served_model": response.model,  # type: ignore[union-attr]
        "served_provider": response.provider,  # type: ignore[union-attr]
    }


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
    metadata: dict[str, str | int] | None = None,
    reference_image: str | None = None,
    reference_mime_type: str | None = None,
) -> dict[str, object]:
    """Generate an image and persist a design asset."""
    normalized_type, (width, height), resolved_model = normalize_asset_type(asset_type), parse_size(size), _resolve_model(model)
    merged_prompt = build_generation_prompt(
        asset_type=normalized_type, prompt=prompt, style_prompt=style_prompt,
        negative_prompt=negative_prompt, background=background, width=width, height=height,
        transparent_background=transparent_background, sheet_columns=sheet_columns,
        sheet_rows=sheet_rows, frame_width=frame_width, frame_height=frame_height, animation_labels=animation_labels,
    )
    asset_id, image_path, rsp = _generate_and_save(
        project_id=project_id, normalized_type=normalized_type, merged_prompt=merged_prompt,
        style_prompt=style_prompt, reference_image=reference_image, reference_mime_type=reference_mime_type,
        width=width, height=height, resolved_model=resolved_model,
    )
    return _persist_asset(
        project_id, asset_id, image_path, name=name, description=description,
        normalized_type=normalized_type, workflow=workflow, merged_prompt=merged_prompt,
        negative_prompt=negative_prompt, style_prompt=style_prompt, background=background,
        width=width, height=height, transparent_background=transparent_background,
        served_model=rsp.model,  # type: ignore[union-attr]
        generator=generator, source_asset_id=source_asset_id, sheet_columns=sheet_columns,
        sheet_rows=sheet_rows, frame_width=frame_width, frame_height=frame_height,
        animation_labels=animation_labels, tags=tags,
        extra_metadata=_make_served_metadata(metadata, resolved_model, rsp),
    )


# ---------------------------------------------------------------------------
# Sprite sheet export helpers
# ---------------------------------------------------------------------------


def _validate_sheet_asset(asset: dict[str, object]) -> tuple[int, int, int, int]:
    """Validate sprite sheet metadata and return (frame_w, frame_h, cols, rows)."""
    if not asset.get("file_path"):
        raise ValueError("Asset has no file to export")
    if asset["asset_type"] != "sprite_sheet":
        raise ValueError("Only sprite sheet assets support frame exports")
    frame_w = asset.get("frame_width")
    frame_h = asset.get("frame_height")
    cols = asset.get("sheet_columns")
    rows = asset.get("sheet_rows")
    if not all([frame_w, frame_h, cols, rows]):
        raise ValueError("Sprite sheet export requires frame dimensions and grid metadata")
    return int(frame_w), int(frame_h), int(cols), int(rows)


def _slice_frames(
    image_path: Path,
    export_dir: Path,
    *,
    frame_width: int,
    frame_height: int,
    sheet_columns: int,
    sheet_rows: int,
    animation_labels: list[str],
) -> dict[str, dict[str, dict[str, int]]]:
    """Crop each frame from the sheet and save PNGs; return atlas frame metadata."""
    atlas_frames: dict[str, dict[str, dict[str, int]]] = {}
    with Image.open(image_path) as image:
        for row in range(sheet_rows):
            for col in range(sheet_columns):
                left = col * frame_width
                top = row * frame_height
                frame = image.crop((left, top, left + frame_width, top + frame_height))
                animation = animation_labels[row] if row < len(animation_labels) else f"row-{row + 1}"
                frame_name = f"{animation}_{col + 1:02d}.png"
                frame.save(export_dir / frame_name)
                atlas_frames[frame_name] = {
                    "frame": {"x": left, "y": top, "w": frame_width, "h": frame_height},
                    "sourceSize": {"w": frame_width, "h": frame_height},
                }
    return atlas_frames


def _write_atlas_manifest(
    manifest_path: Path,
    atlas_frames: dict[str, dict[str, dict[str, int]]],
    asset: dict[str, object],
    frame_width: int,
    frame_height: int,
) -> None:
    """Serialise the atlas manifest JSON to disk."""
    manifest = {
        "frames": atlas_frames,
        "meta": {
            "app": _META_APP,
            "asset_id": asset["asset_id"],
            "size": {"w": asset["width"], "h": asset["height"]},
            "frame_size": {"w": frame_width, "h": frame_height},
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def export_sprite_sheet_frames(asset: dict[str, object]) -> dict[str, object]:
    """Slice a sprite sheet into frame exports plus a JSON atlas manifest."""
    frame_width, frame_height, sheet_columns, sheet_rows = _validate_sheet_asset(asset)

    image_path = Path(str(asset["file_path"]))
    if not image_path.exists():
        raise FileNotFoundError(f"Asset image not found: {image_path}")

    export_dir = image_path.parent / "exports" / "frames"
    export_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = image_path.parent / "exports" / "atlas.json"

    animation_labels: list[str] = list(asset.get("animation_labels") or [])
    atlas_frames = _slice_frames(
        image_path,
        export_dir,
        frame_width=frame_width,
        frame_height=frame_height,
        sheet_columns=sheet_columns,
        sheet_rows=sheet_rows,
        animation_labels=animation_labels,
    )
    _write_atlas_manifest(manifest_path, atlas_frames, asset, frame_width, frame_height)

    frame_count = sheet_columns * sheet_rows
    export_record = design_assets.create_asset_export(
        asset["id"],
        "sprite_frames",
        str(export_dir),
        manifest_path=str(manifest_path),
        metadata={"frame_count": frame_count, "frame_width": frame_width, "frame_height": frame_height},
    )
    design_assets.create_asset_export(
        asset["id"],
        "atlas_json",
        str(manifest_path),
        metadata={"frame_count": frame_count},
    )
    return export_record
