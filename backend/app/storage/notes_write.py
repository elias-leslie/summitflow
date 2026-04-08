"""Notes write layer - create, update, and delete operations."""

from __future__ import annotations

import json
from typing import Any

from ._sql import static_sql
from .connection import generate_prefixed_id, get_connection
from .notes_helpers import NoteType, _row_to_dict, normalize_project_scope

_RETURNING_COLS = (
    "RETURNING id, project_scope, type, title, content, tags, pinned, metadata,"
    " created_at, updated_at"
)


def create_note(
    title: str,
    content: str = "",
    project_scope: str = "global",
    note_type: NoteType = "note",
    tags: list[str] | None = None,
    pinned: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new note."""
    note_id = generate_prefixed_id("note")
    meta_json = json.dumps(metadata or {})
    normalized_scope = normalize_project_scope(project_scope)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            static_sql(
                f"""
                INSERT INTO notes (id, project_scope, type, title, content, tags, pinned, metadata)
                VALUES (%s, %s, %s, %s, %s, %s::text[], %s, %s::jsonb)
                {_RETURNING_COLS}
                """
            ),
            (note_id, normalized_scope, note_type, title, content, tags or [], pinned, meta_json),
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)


def update_note(note_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update a note. Only provided fields are updated.

    Supported fields: title, content, project_scope, type, tags, pinned, metadata.
    """
    if not fields:
        from .notes_query import get_note

        return get_note(note_id)

    set_parts: list[str] = []
    params: list[Any] = []

    for key, value in fields.items():
        if key == "tags":
            set_parts.append("tags = %s::text[]")
            params.append(value)
        elif key == "metadata":
            set_parts.append("metadata = %s::jsonb")
            params.append(json.dumps(value))
        elif key == "project_scope":
            set_parts.append("project_scope = %s")
            params.append(normalize_project_scope(value))
        else:
            set_parts.append(f"{key} = %s")
            params.append(value)

    set_parts.append("updated_at = NOW()")
    params.append(note_id)

    query = static_sql(f"UPDATE notes SET {', '.join(set_parts)} WHERE id = %s {_RETURNING_COLS}")

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row) if row else None


def delete_note(note_id: str) -> bool:
    """Delete a note. Returns True if deleted, False if not found."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM notes WHERE id = %s RETURNING id", (note_id,))
        result = cur.fetchone()
        conn.commit()
    return result is not None
