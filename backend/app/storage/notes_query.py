"""Notes query helpers - read-only DB access for notes."""

from __future__ import annotations

from typing import Any

from ._sql import static_sql
from .connection import get_cursor
from .notes_helpers import NoteType, _row_to_dict

_SELECT_COLS = """
    SELECT id, project_scope, type, title, content, tags, pinned, metadata,
           created_at, updated_at
    FROM notes
"""


def get_note(note_id: str) -> dict[str, Any] | None:
    """Get a note by ID."""
    with get_cursor() as cur:
        cur.execute(static_sql(_SELECT_COLS + "WHERE id = %s"), (note_id,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_notes(
    *,
    project_scope: str | None = None,
    note_type: NoteType | None = None,
    tags: list[str] | None = None,
    search: str | None = None,
    pinned: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List notes with optional filters.

    Args:
        project_scope: Filter by project scope (e.g. 'summitflow', 'global')
        note_type: Filter by type ('note' or 'prompt')
        tags: Filter by tags (AND match via @> array contains)
        search: Full-text search across title and content (ILIKE)
        pinned: Filter by pinned status
        limit: Max results (default 50)
        offset: Result offset
    """
    conditions: list[str] = []
    params: list[Any] = []

    if project_scope is not None:
        conditions.append("project_scope = %s")
        params.append(project_scope)
    if note_type is not None:
        conditions.append("type = %s")
        params.append(note_type)
    if tags:
        conditions.append("tags @> %s::text[]")
        params.append(tags)
    if search:
        conditions.append("(title ILIKE %s OR content ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    if pinned is not None:
        conditions.append("pinned = %s")
        params.append(pinned)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    query = _SELECT_COLS + where + " ORDER BY pinned DESC, updated_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with get_cursor() as cur:
        cur.execute(static_sql(query), params)
        rows = cur.fetchall()
    return [_row_to_dict(row) for row in rows]


def count_notes(
    *,
    project_scope: str | None = None,
    note_type: NoteType | None = None,
    tags: list[str] | None = None,
    search: str | None = None,
    pinned: bool | None = None,
) -> int:
    """Count notes matching the given filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if project_scope is not None:
        conditions.append("project_scope = %s")
        params.append(project_scope)
    if note_type is not None:
        conditions.append("type = %s")
        params.append(note_type)
    if tags:
        conditions.append("tags @> %s::text[]")
        params.append(tags)
    if search:
        conditions.append("(title ILIKE %s OR content ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    if pinned is not None:
        conditions.append("pinned = %s")
        params.append(pinned)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    query = "SELECT COUNT(*) FROM notes" + where

    with get_cursor() as cur:
        cur.execute(static_sql(query), params)
        row = cur.fetchone()
    return row[0] if row else 0


def list_tags(project_scope: str | None = None) -> list[str]:
    """Get all distinct tags, optionally filtered by project scope."""
    if project_scope:
        query = "SELECT DISTINCT unnest(tags) AS tag FROM notes WHERE project_scope = %s ORDER BY tag"
        params: tuple[Any, ...] = (project_scope,)
    else:
        query = "SELECT DISTINCT unnest(tags) AS tag FROM notes ORDER BY tag"
        params = ()

    with get_cursor() as cur:
        cur.execute(static_sql(query), params)
        rows = cur.fetchall()
    return [row[0] for row in rows]
