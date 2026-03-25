"""Notes helpers - shared types, constants, and row conversion."""

from __future__ import annotations

from typing import Any, Literal

from psycopg.rows import TupleRow

NoteType = Literal["note", "prompt"]


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a note dict."""
    if row is None:
        raise ValueError("Row cannot be None")
    return {
        "id": row[0],
        "project_scope": row[1],
        "type": row[2],
        "title": row[3],
        "content": row[4],
        "tags": row[5] or [],
        "pinned": row[6],
        "metadata": row[7] or {},
        "created_at": row[8],
        "updated_at": row[9],
    }
