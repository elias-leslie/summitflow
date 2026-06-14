"""Mockups core - Constants, ID generation, row mapping, and create operations."""

from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb

from .._sql import static_sql
from ..connection import get_connection, get_cursor

# Mockup type constants
MOCKUP_TYPES = frozenset(
    {"component", "page", "layout", "icon", "illustration", "sprite", "sheet"}
)

# Mockup status constants
MOCKUP_STATUSES = frozenset(
    {"generated", "pending_approval", "approved", "rejected", "applied", "archived"}
)

# Base SELECT columns for mockup queries
MOCKUP_COLUMN_NAMES = (
    "id",
    "project_id",
    "mockup_id",
    "name",
    "description",
    "mockup_type",
    "file_path",
    "content",
    "status",
    "approved_at",
    "approved_by",
    "applied_at",
    "task_id",
    "page_path",
    "version",
    "parent_mockup_id",
    "generator",
    "generation_prompt",
    "generation_time_ms",
    "iteration_count",
    "metadata",
    "created_at",
    "updated_at",
)
MOCKUP_SELECT_COLUMNS = ", ".join(MOCKUP_COLUMN_NAMES)
MOCKUP_SELECT_COLUMNS_ALIASED = ", ".join(f"m.{column}" for column in MOCKUP_COLUMN_NAMES)
MOCKUP_RATING_SELECT_COLUMNS = """
       COALESCE(rating_counts.rating_average, 0) AS rating_average,
       COALESCE(rating_counts.rating_count, 0) AS rating_count,
       COALESCE(user_rating.rating, 0) AS user_rating
"""
MOCKUP_COMMENT_COUNT_SELECT_COLUMN = (
    "COALESCE(comment_counts.comment_count, 0) AS comment_count"
)

# Default initial mockup version and iteration count
_DEFAULT_VERSION = 1
_DEFAULT_ITERATION = 1

# Default mockup status on creation
_INITIAL_STATUS = "generated"


def generate_mockup_id() -> str:
    """Generate a new mockup ID in the format mk-{uuid}."""
    return f"mk-{uuid.uuid4().hex[:12]}"


def _row_to_mockup(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert database row to mockup dict."""
    rating_average = float(row[23]) if len(row) > 23 and row[23] is not None else 0.0
    rating_count = int(row[24]) if len(row) > 24 and row[24] is not None else 0
    comment_count = int(row[26]) if len(row) > 26 and row[26] is not None else 0
    return {
        "id": row[0],
        "project_id": row[1],
        "mockup_id": row[2],
        "name": row[3],
        "description": row[4],
        "mockup_type": row[5],
        "file_path": row[6],
        "content": row[7],
        "status": row[8],
        "approved_at": row[9].isoformat() if row[9] else None,
        "approved_by": row[10],
        "applied_at": row[11].isoformat() if row[11] else None,
        "task_id": row[12],
        "page_path": row[13],
        "version": row[14],
        "parent_mockup_id": row[15],
        "generator": row[16],
        "generation_prompt": row[17],
        "generation_time_ms": row[18],
        "iteration_count": row[19],
        "metadata": row[20] or {},
        "created_at": row[21].isoformat() if row[21] else None,
        "updated_at": row[22].isoformat() if row[22] else None,
        "rating_average": rating_average,
        "rating_count": rating_count,
        "user_rating": int(row[25]) if len(row) > 25 and row[25] is not None else 0,
        "comment_count": comment_count,
    }


def get_mockup_by_db_id(db_id: int) -> dict[str, Any] | None:
    """Get a mockup by database ID (primary key)."""
    with get_cursor() as cur:
        cur.execute(
            static_sql(f"SELECT {MOCKUP_SELECT_COLUMNS} FROM mockups WHERE id = %s"),
            (db_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return _row_to_mockup(row)


def _resolve_version_and_iteration(parent_mockup_id: int | None) -> tuple[int, int]:
    """Return (version, iteration_count) based on parent mockup, or defaults."""
    if not parent_mockup_id:
        return _DEFAULT_VERSION, _DEFAULT_ITERATION
    parent = get_mockup_by_db_id(parent_mockup_id)
    if not parent:
        return _DEFAULT_VERSION, _DEFAULT_ITERATION
    return parent["version"] + 1, parent["iteration_count"] + 1


def _insert_mockup_row(params: tuple[Any, ...]) -> dict[str, Any]:
    """Execute the INSERT for a new mockup and return the resulting row dict."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            static_sql(
                f"""
            INSERT INTO mockups (
                project_id, mockup_id, name, description, mockup_type,
                file_path, content, status, task_id, page_path,
                version, parent_mockup_id, generator, generation_prompt,
                generation_time_ms, iteration_count, metadata
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, '{_INITIAL_STATUS}',
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING {MOCKUP_SELECT_COLUMNS}
            """
            ),
            params,
        )
        row = cur.fetchone()
        conn.commit()
    if not row:
        raise RuntimeError("Failed to create mockup record")
    return _row_to_mockup(row)


def create_mockup(
    project_id: str,
    name: str,
    *,
    description: str | None = None,
    mockup_type: str = "component",
    file_path: str | None = None,
    content: str | None = None,
    task_id: str | None = None,
    page_path: str | None = None,
    parent_mockup_id: int | None = None,
    generator: str | None = None,
    generation_prompt: str | None = None,
    generation_time_ms: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new mockup record and return it."""
    if mockup_type not in MOCKUP_TYPES:
        raise ValueError(f"Invalid mockup_type: {mockup_type}. Must be one of {MOCKUP_TYPES}")
    mockup_id = generate_mockup_id()
    version, iteration_count = _resolve_version_and_iteration(parent_mockup_id)
    return _insert_mockup_row(
        (
            project_id,
            mockup_id,
            name,
            description,
            mockup_type,
            file_path,
            content,
            task_id,
            page_path,
            version,
            parent_mockup_id,
            generator,
            generation_prompt,
            generation_time_ms,
            iteration_count,
            Jsonb(metadata or {}),
        )
    )
