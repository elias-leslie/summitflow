"""Content search primitive over indexed project files."""

from __future__ import annotations

from typing import Any

from ...storage import explorer as explorer_storage
from ..file_browser import read_file
from .base import get_project_root

_MAX_TEXT_RESULTS = 100
_MAX_FILE_ENTRIES = 10_000
_LINE_PREVIEW_LIMIT = 240


def search_text(project_id: str, query: str, *, limit: int = 20) -> dict[str, Any]:
    """Search indexed project files for case-insensitive line matches."""
    query_value = query.strip()
    if not query_value:
        return {"count": 0, "files_searched": 0, "items": [], "truncated": False}

    root_path = get_project_root(project_id)
    if not root_path:
        return {"count": 0, "files_searched": 0, "items": [], "truncated": False}

    capped_limit = max(1, min(limit, _MAX_TEXT_RESULTS))
    query_lower = query_value.lower()
    items: list[dict[str, Any]] = []
    files_searched = 0

    file_entries = explorer_storage.get_entries(
        project_id,
        filters={
            "type": "file",
            "sort": "path",
            "dir": "asc",
            "limit": _MAX_FILE_ENTRIES,
            "offset": 0,
        },
    )

    for entry in file_entries:
        path = str(entry.get("path", "")).strip()
        if not path:
            continue

        try:
            file_data = read_file(root_path, path)
        except (FileNotFoundError, PermissionError, ValueError):
            continue

        if file_data.get("is_binary") or file_data.get("content") is None:
            continue

        files_searched += 1
        content = str(file_data.get("content", ""))
        for line_number, line in enumerate(content.splitlines(), start=1):
            if query_lower not in line.lower():
                continue

            items.append(
                {
                    "path": path,
                    "line": line_number,
                    "content": line.rstrip()[:_LINE_PREVIEW_LIMIT],
                    "language": file_data.get("language"),
                    "truncated_file": bool(file_data.get("truncated")),
                }
            )
            if len(items) >= capped_limit:
                return {
                    "count": len(items),
                    "files_searched": files_searched,
                    "items": items,
                    "truncated": True,
                }

    return {
        "count": len(items),
        "files_searched": files_searched,
        "items": items,
        "truncated": False,
    }
