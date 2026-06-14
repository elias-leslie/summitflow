"""Design asset generation and export workflow helpers."""

from __future__ import annotations

import base64
import binascii
import contextlib
import io
import json
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image

from ..constants import AGENT_IMAGE_GEN
from ..services.agent_hub_client import get_sync_client
from ..storage import design_assets
from .mockup_generator.storage_helpers import get_mockup_directory

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/svg+xml": "svg",
    "image/webp": "webp",
}
_IMPORT_MIME_TYPES = frozenset(_MIME_TO_EXT)

_BACKGROUND_TRANSPARENT = "transparent"
_PURPOSE_DESIGN_ASSET = "design_asset_generation"
_META_APP = "summitflow"

# Asset type groups
_COMPOSITE_ASSET_TYPES = frozenset({"sprite", "icon", "ui_texture", "portrait"})
_SCENE_ASSET_TYPES = frozenset({"environment", "concept_art", "marketing_mockup"})
_SVG_DENIED_TAGS = frozenset({"script", "foreignobject"})


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
# Agent resolution helpers
# ---------------------------------------------------------------------------


def _resolve_agent_slug(agent_slug: str | None, legacy_agent_or_model: str | None = None) -> str:
    """Resolve an image generation agent slug.

    Legacy model IDs are intentionally ignored; Agent Hub owns image model choice.
    """
    candidate = agent_slug or legacy_agent_or_model
    if candidate and "/" not in candidate:
        return candidate.removeprefix("agent:")
    return AGENT_IMAGE_GEN


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------


def _call_image_api(
    *,
    client: object,
    agent_slug: str,
    prompt: str,
    project_id: str,
    width: int,
    height: int,
    style_prompt: str | None,
    reference_image: str | None,
    reference_mime_type: str | None,
) -> object:
    """Generate through the assigned Agent Hub image agent."""
    return client.generate_image(  # type: ignore[union-attr]
        prompt=prompt,
        project_id=project_id,
        purpose=_PURPOSE_DESIGN_ASSET,
        agent_slug=agent_slug,
        size=f"{width}x{height}",
        style=style_prompt,
        reference_image=reference_image,
        reference_mime_type=reference_mime_type,
    )


def _save_image_file(project_id: str, asset_id: str, image_bytes: bytes, ext: str) -> Path:
    """Write image bytes to disk and return the path."""
    asset_dir = get_mockup_directory(project_id, asset_id)
    asset_dir.mkdir(parents=True, exist_ok=True)
    image_path = asset_dir / f"asset.{ext}"
    image_path.write_bytes(image_bytes)
    return image_path


def _strip_svg_unit(value: str) -> int | None:
    """Coerce an SVG length like '1024px' to an integer pixel value."""
    text = value.strip().lower().removesuffix("px")
    with contextlib.suppress(ValueError):
        return int(float(text))
    return None


def _xml_local_name(value: str) -> str:
    """Return a lower-case XML local name without the namespace."""
    return value.rsplit("}", 1)[-1].lower()


def _validate_svg_root(root: ElementTree.Element) -> None:
    """Reject active SVG content before storing user/manual imports."""
    for element in root.iter():
        if _xml_local_name(element.tag) in _SVG_DENIED_TAGS:
            raise ValueError("SVG asset contains unsupported active content")
        for attr, value in element.attrib.items():
            attr_name = _xml_local_name(attr)
            if attr_name.startswith("on"):
                raise ValueError("SVG asset contains unsupported active content")
            if attr_name == "href" and value.strip().lower().startswith("javascript:"):
                raise ValueError("SVG asset contains unsupported active content")


def _svg_dimensions(image_bytes: bytes) -> tuple[int, int]:
    """Extract SVG dimensions from width/height or viewBox."""
    try:
        root = ElementTree.fromstring(image_bytes)
    except ElementTree.ParseError as exc:
        raise ValueError("Invalid SVG asset") from exc
    _validate_svg_root(root)

    width = _strip_svg_unit(root.attrib.get("width", ""))
    height = _strip_svg_unit(root.attrib.get("height", ""))
    if width and height:
        return width, height

    view_box = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if view_box:
        parts = view_box.replace(",", " ").split()
        if len(parts) == 4:
            with contextlib.suppress(ValueError):
                return int(float(parts[2])), int(float(parts[3]))

    raise ValueError("SVG asset needs width/height or viewBox")


def _image_dimensions(image_bytes: bytes, mime_type: str) -> tuple[int, int]:
    """Read image dimensions without trusting caller-provided metadata."""
    if mime_type == "image/svg+xml":
        return _svg_dimensions(image_bytes)
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            return image.size
    except Exception as exc:
        raise ValueError("Invalid image asset") from exc


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
    extra_metadata: dict[str, object],
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
    merged_prompt: str,
    style_prompt: str | None,
    reference_image: str | None,
    reference_mime_type: str | None,
    width: int,
    height: int,
    agent_slug: str,
) -> tuple[str, Path, object]:
    """Call the image API and write the result to disk; return (asset_id, image_path, response)."""
    response = _call_image_api(
        client=get_sync_client(), agent_slug=agent_slug, prompt=merged_prompt,
        project_id=project_id, width=width, height=height, style_prompt=style_prompt,
        reference_image=reference_image, reference_mime_type=reference_mime_type,
    )
    image_bytes = base64.b64decode(response.image_base64)  # type: ignore[union-attr]
    ext = _MIME_TO_EXT.get(response.mime_type, "png")  # type: ignore[union-attr]
    asset_id = design_assets.generate_asset_id()
    return asset_id, _save_image_file(project_id, asset_id, image_bytes, ext), response


def _make_served_metadata(
    base: dict[str, str | int] | None, agent_slug: str, response: object,
) -> dict[str, object]:
    """Merge caller metadata with provider telemetry fields."""
    return {
        **(base or {}),
        "requested_agent": agent_slug,
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
    agent_slug: str | None = None,
    model: str | None = None,
    generator: str = "image-gen",
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
    normalized_type, (width, height), resolved_agent_slug = (
        normalize_asset_type(asset_type),
        parse_size(size),
        _resolve_agent_slug(agent_slug, model),
    )
    merged_prompt = build_generation_prompt(
        asset_type=normalized_type, prompt=prompt, style_prompt=style_prompt,
        negative_prompt=negative_prompt, background=background, width=width, height=height,
        transparent_background=transparent_background, sheet_columns=sheet_columns,
        sheet_rows=sheet_rows, frame_width=frame_width, frame_height=frame_height, animation_labels=animation_labels,
    )
    asset_id, image_path, rsp = _generate_and_save(
        project_id=project_id, merged_prompt=merged_prompt,
        style_prompt=style_prompt, reference_image=reference_image, reference_mime_type=reference_mime_type,
        width=width, height=height, agent_slug=resolved_agent_slug,
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
        extra_metadata=_make_served_metadata(metadata, resolved_agent_slug, rsp),
    )


def import_asset_image(
    *,
    project_id: str,
    name: str,
    image_base64: str,
    mime_type: str,
    original_file_name: str | None,
    prompt: str,
    description: str | None,
    asset_type: str,
    workflow: str,
    background: str,
    transparent_background: bool,
    source_asset_id: int | None = None,
    sheet_columns: int | None = None,
    sheet_rows: int | None = None,
    frame_width: int | None = None,
    frame_height: int | None = None,
    animation_labels: list[str] | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Persist a manually supplied image as a Design Studio asset.

    This path is intentionally not routed through Agent Hub. It is for assets
    generated or authored by the current agent/user and then queued in Asset
    Studio for the normal approval lifecycle.
    """
    normalized_type = normalize_asset_type(asset_type)
    normalized_mime = mime_type.lower().split(";")[0].strip()
    if normalized_mime not in _IMPORT_MIME_TYPES:
        raise ValueError("Manual asset import supports PNG, JPEG, WebP, and SVG images")
    try:
        image_bytes = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid base64 image payload") from exc
    width, height = _image_dimensions(image_bytes, normalized_mime)
    asset_id = design_assets.generate_asset_id()
    image_path = _save_image_file(project_id, asset_id, image_bytes, _MIME_TO_EXT[normalized_mime])
    return _persist_asset(
        project_id, asset_id, image_path,
        name=name,
        description=description,
        normalized_type=normalized_type,
        workflow=workflow,
        merged_prompt=prompt,
        negative_prompt=None,
        style_prompt=None,
        background=background,
        width=width,
        height=height,
        transparent_background=transparent_background,
        served_model="manual",
        generator="manual-image",
        source_asset_id=source_asset_id,
        sheet_columns=sheet_columns,
        sheet_rows=sheet_rows,
        frame_width=frame_width,
        frame_height=frame_height,
        animation_labels=animation_labels,
        tags=tags,
        extra_metadata={
            **(metadata or {}),
            "source": "manual-import",
            "mime_type": normalized_mime,
            "original_file_name": original_file_name or "",
        },
    )


# ---------------------------------------------------------------------------
# Sprite sheet export helpers
# ---------------------------------------------------------------------------


def _coerce_positive_int(value: object) -> int | None:
    """Coerce sprite-sheet metadata values to positive integers."""
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        coerced = int(value)
        return coerced if coerced > 0 else None
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            coerced = int(value)
            return coerced if coerced > 0 else None
    return None


def _validate_sheet_asset(asset: dict[str, object]) -> tuple[int, int, int, int]:
    """Validate sprite sheet metadata and return (frame_w, frame_h, cols, rows)."""
    if not asset.get("file_path"):
        raise ValueError("Asset has no file to export")
    if asset["asset_type"] != "sprite_sheet":
        raise ValueError("Only sprite sheet assets support frame exports")
    frame_w = _coerce_positive_int(asset.get("frame_width"))
    frame_h = _coerce_positive_int(asset.get("frame_height"))
    cols = _coerce_positive_int(asset.get("sheet_columns"))
    rows = _coerce_positive_int(asset.get("sheet_rows"))
    if frame_w is None or frame_h is None or cols is None or rows is None:
        raise ValueError("Sprite sheet export requires frame dimensions and grid metadata")
    return frame_w, frame_h, cols, rows


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
    asset_id = asset.get("id")
    if not isinstance(asset_id, int):
        raise ValueError("Sprite sheet asset is missing a valid database id")

    image_path = Path(str(asset["file_path"]))
    if not image_path.exists():
        raise FileNotFoundError(f"Asset image not found: {image_path}")

    export_dir = image_path.parent / "exports" / "frames"
    export_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = image_path.parent / "exports" / "atlas.json"

    animation_labels_value = asset.get("animation_labels")
    animation_labels: list[str] = (
        [str(label) for label in animation_labels_value]
        if isinstance(animation_labels_value, list)
        else []
    )
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
        asset_id,
        "sprite_frames",
        str(export_dir),
        manifest_path=str(manifest_path),
        metadata={"frame_count": frame_count, "frame_width": frame_width, "frame_height": frame_height},
    )
    design_assets.create_asset_export(
        asset_id,
        "atlas_json",
        str(manifest_path),
        metadata={"frame_count": frame_count},
    )
    return export_record
