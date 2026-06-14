"""Core helpers for first-class generated design assets."""

from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb

from .._sql import static_sql
from ..connection import get_connection, get_cursor

ASSET_TYPES = frozenset(
    {
        "sprite",
        "sprite_sheet",
        "portrait",
        "environment",
        "icon",
        "illustration",
        "ui_texture",
        "marketing_mockup",
        "tile_set",
        "concept_art",
    }
)
ASSET_WORKFLOWS = frozenset({"concept", "production", "marketing", "ui"})
ASSET_STATUSES = frozenset({"generated", "approved", "rejected", "archived", "exported"})
ASSET_BACKGROUNDS = frozenset({"transparent", "solid", "scene"})
EXPORT_TYPES = frozenset({"original", "sprite_frames", "atlas_json"})

ASSET_COLUMN_NAMES = [
    "id",
    "project_id",
    "asset_id",
    "name",
    "description",
    "asset_type",
    "workflow",
    "status",
    "prompt",
    "negative_prompt",
    "style_prompt",
    "background",
    "width",
    "height",
    "transparent_background",
    "model",
    "generator",
    "file_path",
    "source_asset_id",
    "sheet_columns",
    "sheet_rows",
    "frame_width",
    "frame_height",
    "animation_labels",
    "tags",
    "metadata",
    "approved_at",
    "approved_by",
    "created_at",
    "updated_at",
]
ASSET_SELECT_COLUMNS = ", ".join(ASSET_COLUMN_NAMES)
ASSET_SELECT_COLUMNS_ALIASED = ", ".join(f"a.{column}" for column in ASSET_COLUMN_NAMES)
ASSET_RATING_SELECT_COLUMNS = """COALESCE(rating_counts.rating_average, 0) AS rating_average,
       COALESCE(rating_counts.rating_count, 0) AS rating_count,
       COALESCE(user_rating.rating, 0) AS user_rating"""
ASSET_COMMENT_COUNT_SELECT_COLUMN = (
    "COALESCE(comment_counts.comment_count, 0) AS comment_count"
)

EXPORT_SELECT_COLUMNS = """id, asset_id, export_id, export_type, file_path, manifest_path,
       metadata, created_at"""


def generate_asset_id() -> str:
    """Generate a new asset id."""
    return f"asset-{uuid.uuid4().hex[:12]}"


def generate_export_id() -> str:
    """Generate a new export id."""
    return f"export-{uuid.uuid4().hex[:12]}"


def _row_to_asset(row: tuple[Any, ...]) -> dict[str, Any]:
    """Map a database row to an asset payload."""
    return {
        "id": row[0],
        "project_id": row[1],
        "asset_id": row[2],
        "name": row[3],
        "description": row[4],
        "asset_type": row[5],
        "workflow": row[6],
        "status": row[7],
        "prompt": row[8],
        "negative_prompt": row[9],
        "style_prompt": row[10],
        "background": row[11],
        "width": row[12],
        "height": row[13],
        "transparent_background": row[14],
        "model": row[15],
        "generator": row[16],
        "file_path": row[17],
        "source_asset_id": row[18],
        "sheet_columns": row[19],
        "sheet_rows": row[20],
        "frame_width": row[21],
        "frame_height": row[22],
        "animation_labels": row[23] or [],
        "tags": row[24] or [],
        "metadata": row[25] or {},
        "approved_at": row[26].isoformat() if row[26] else None,
        "approved_by": row[27],
        "created_at": row[28].isoformat() if row[28] else None,
        "updated_at": row[29].isoformat() if row[29] else None,
        "rating_average": float(row[30] or 0) if len(row) > 30 else 0.0,
        "rating_count": int(row[31] or 0) if len(row) > 31 else 0,
        "user_rating": int(row[32] or 0) if len(row) > 32 else 0,
        "comment_count": int(row[33] or 0) if len(row) > 33 else 0,
    }


def _row_to_export(row: tuple[Any, ...]) -> dict[str, Any]:
    """Map a database row to an export payload."""
    return {
        "id": row[0],
        "asset_db_id": row[1],
        "export_id": row[2],
        "export_type": row[3],
        "file_path": row[4],
        "manifest_path": row[5],
        "metadata": row[6] or {},
        "created_at": row[7].isoformat() if row[7] else None,
    }


def get_asset_by_db_id(db_id: int) -> dict[str, Any] | None:
    """Get asset by database id."""
    with get_cursor() as cur:
        cur.execute(static_sql(f"SELECT {ASSET_SELECT_COLUMNS} FROM design_assets WHERE id = %s"), (db_id,))
        row = cur.fetchone()
    return _row_to_asset(row) if row else None


def create_asset(
    project_id: str,
    name: str,
    *,
    asset_id: str | None = None,
    asset_type: str,
    workflow: str,
    prompt: str,
    width: int,
    height: int,
    background: str,
    transparent_background: bool,
    description: str | None = None,
    negative_prompt: str | None = None,
    style_prompt: str | None = None,
    model: str | None = None,
    generator: str | None = None,
    file_path: str | None = None,
    source_asset_id: int | None = None,
    sheet_columns: int | None = None,
    sheet_rows: int | None = None,
    frame_width: int | None = None,
    frame_height: int | None = None,
    animation_labels: list[str] | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a design asset."""
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"Invalid asset_type: {asset_type}")
    if workflow not in ASSET_WORKFLOWS:
        raise ValueError(f"Invalid workflow: {workflow}")
    if background not in ASSET_BACKGROUNDS:
        raise ValueError(f"Invalid background: {background}")

    asset_id = asset_id or generate_asset_id()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            static_sql(
                f"""
            INSERT INTO design_assets (
                project_id, asset_id, name, description, asset_type, workflow, status,
                prompt, negative_prompt, style_prompt, background, width, height,
                transparent_background, model, generator, file_path, source_asset_id,
                sheet_columns, sheet_rows, frame_width, frame_height, animation_labels,
                tags, metadata
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, 'generated',
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s
            )
            RETURNING {ASSET_SELECT_COLUMNS}
            """
            ),
            (
                project_id,
                asset_id,
                name,
                description,
                asset_type,
                workflow,
                prompt,
                negative_prompt,
                style_prompt,
                background,
                width,
                height,
                transparent_background,
                model,
                generator,
                file_path,
                source_asset_id,
                sheet_columns,
                sheet_rows,
                frame_width,
                frame_height,
                animation_labels or [],
                tags or [],
                Jsonb(metadata or {}),
            ),
        )
        row = cur.fetchone()
        conn.commit()
    if not row:
        raise RuntimeError("Failed to create design asset")
    return _row_to_asset(row)


def create_asset_export(
    asset_db_id: int,
    export_type: str,
    file_path: str,
    *,
    manifest_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an asset export record."""
    if export_type not in EXPORT_TYPES:
        raise ValueError(f"Invalid export_type: {export_type}")
    export_id = generate_export_id()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO design_asset_exports (
                asset_id, export_id, export_type, file_path, manifest_path, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING {EXPORT_SELECT_COLUMNS}
            """,
            (asset_db_id, export_id, export_type, file_path, manifest_path, Jsonb(metadata or {})),
        )
        row = cur.fetchone()
        conn.commit()
    if not row:
        raise RuntimeError("Failed to create asset export")
    return _row_to_export(row)
