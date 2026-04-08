"""Notes storage layer - Note and prompt CRUD.

Query helpers live in notes_query.py; shared types in notes_helpers.py.
Write operations live in notes_write.py.
"""

from __future__ import annotations

from .notes_helpers import NoteType
from .notes_query import count_notes, get_note, list_notes, list_project_scopes, list_tags
from .notes_write import create_note, delete_note, update_note

__all__ = [
    "NoteType",
    "count_notes",
    "create_note",
    "delete_note",
    "get_note",
    "list_notes",
    "list_project_scopes",
    "list_tags",
    "update_note",
]
