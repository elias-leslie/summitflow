"""Content search primitive over indexed project files."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...storage import explorer as explorer_storage
from ..file_browser import read_file
from .base import get_project_root

logger = get_logger(__name__)

_MAX_TEXT_RESULTS = 100
_MAX_FILE_ENTRIES = 10_000
_LINE_PREVIEW_LIMIT = 240
_RG_TIMEOUT_SECONDS = 15
_RG_EXCLUDE_GLOBS = (
    "!**/.git/**",
    "!**/node_modules/**",
    "!**/.venv/**",
    "!**/.next/**",
    "!**/dist/**",
    "!**/build/**",
    "!**/coverage/**",
)


def _normalize_path_prefix(path_prefix: str | None) -> str | None:
    """Normalize an optional relative subtree/file prefix for search filtering."""
    if path_prefix is None:
        return None
    normalized = str(path_prefix).strip().replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.strip("/")
    return normalized or None


def _path_matches_prefix(path: str, path_prefix: str | None) -> bool:
    """Return True when path falls under the requested prefix (or no prefix provided)."""
    if not path_prefix:
        return True
    return path == path_prefix or path.startswith(f"{path_prefix}/")


def _fallback_file_total(project_id: str) -> int:
    stats = explorer_storage.get_stats(project_id, entry_type="file")
    return int(stats.get("total") or 0)


def _extract_rg_path(path_data: Any) -> str:
    if isinstance(path_data, dict):
        if isinstance(path_data.get("text"), str):
            path = str(path_data["text"])
            return path[2:] if path.startswith("./") else path
        if isinstance(path_data.get("bytes"), str):
            path = str(path_data["bytes"])
            return path[2:] if path.startswith("./") else path
    if isinstance(path_data, str):
        return path_data[2:] if path_data.startswith("./") else path_data
    return ""


def _search_text_with_ripgrep(
    project_id: str,
    root_path: str,
    query: str,
    *,
    limit: int,
    path_prefix: str | None = None,
) -> dict[str, Any] | None:
    rg_path = shutil.which("rg")
    if not rg_path:
        return None

    normalized_prefix = _normalize_path_prefix(path_prefix)
    if normalized_prefix:
        target_path = (Path(root_path) / normalized_prefix).resolve()
        if not target_path.exists():
            return {
                "count": 0,
                "files_searched": 0,
                "items": [],
                "truncated": False,
                "strategy": "ripgrep",
                "path_prefix": normalized_prefix,
            }

    args = [
        rg_path,
        "--json",
        "--line-number",
        "--ignore-case",
        "--fixed-strings",
        "--hidden",
    ]
    for glob in _RG_EXCLUDE_GLOBS:
        args.extend(["--glob", glob])
    args.extend([query, normalized_prefix or "."])

    try:
        proc = subprocess.run(
            args,
            cwd=root_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_RG_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("text_search_ripgrep_failed", project_id=project_id, error=str(exc))
        return None

    if proc.returncode not in (0, 1):
        logger.warning(
            "text_search_ripgrep_nonzero",
            project_id=project_id,
            returncode=proc.returncode,
            stderr=(proc.stderr or "")[-400:],
        )
        return None

    items: list[dict[str, Any]] = []
    total_matches = 0
    files_searched = 0

    for raw_line in proc.stdout.splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        event_type = str(event.get("type", ""))
        data = event.get("data") or {}
        if event_type == "match":
            total_matches += 1
            if len(items) >= limit:
                continue
            path = _extract_rg_path(data.get("path"))
            line_number = data.get("line_number")
            line_text = str((data.get("lines") or {}).get("text", "")).rstrip("\n")
            if not path or not isinstance(line_number, int) or not _path_matches_prefix(path, normalized_prefix):
                continue
            items.append(
                {
                    "path": path,
                    "line": line_number,
                    "content": line_text[:_LINE_PREVIEW_LIMIT],
                    "language": None,
                    "truncated_file": False,
                }
            )
            continue
        if event_type == "summary":
            stats = data.get("stats") or {}
            if isinstance(stats.get("searches"), int):
                files_searched = int(stats["searches"])

    if files_searched == 0:
        files_searched = _fallback_file_total(project_id)

    return {
        "count": len(items),
        "files_searched": files_searched,
        "items": items,
        "truncated": total_matches > len(items),
        "strategy": "ripgrep",
        "path_prefix": normalized_prefix,
    }


def _search_text_from_index(
    project_id: str,
    root_path: str,
    query_value: str,
    *,
    limit: int,
    path_prefix: str | None = None,
) -> dict[str, Any]:
    """Fallback text search using indexed file entries and file reads."""
    query_lower = query_value.lower()
    normalized_prefix = _normalize_path_prefix(path_prefix)
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
        if not _path_matches_prefix(path, normalized_prefix):
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
            if len(items) >= limit:
                return {
                    "count": len(items),
                    "files_searched": files_searched,
                    "items": items,
                    "truncated": True,
                    "strategy": "indexed_fallback",
                    "path_prefix": normalized_prefix,
                }

    return {
        "count": len(items),
        "files_searched": files_searched,
        "items": items,
        "truncated": False,
        "strategy": "indexed_fallback",
        "path_prefix": normalized_prefix,
    }


def search_text(
    project_id: str,
    query: str,
    *,
    limit: int = 20,
    path_prefix: str | None = None,
) -> dict[str, Any]:
    """Search indexed project files for case-insensitive line matches."""
    query_value = query.strip()
    normalized_prefix = _normalize_path_prefix(path_prefix)
    if not query_value:
        return {
            "count": 0,
            "files_searched": 0,
            "items": [],
            "truncated": False,
            "path_prefix": normalized_prefix,
        }

    root_path = get_project_root(project_id)
    if not root_path:
        return {
            "count": 0,
            "files_searched": 0,
            "items": [],
            "truncated": False,
            "path_prefix": normalized_prefix,
        }

    capped_limit = max(1, min(limit, _MAX_TEXT_RESULTS))
    fast_result = _search_text_with_ripgrep(
        project_id,
        root_path,
        query_value,
        limit=capped_limit,
        path_prefix=normalized_prefix,
    )
    if fast_result is not None:
        return fast_result
    return _search_text_from_index(
        project_id,
        root_path,
        query_value,
        limit=capped_limit,
        path_prefix=normalized_prefix,
    )
