"""Checkout text search helpers for `st search`."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .search_checkout_paths import (
    CHECKOUT_EXCLUDE_GLOBS,
    CHECKOUT_RIPGREP_TIMEOUT_SECONDS,
    LINE_PREVIEW_LIMIT,
    _iter_checkout_files,
    _normalize_rel_path,
    _path_matches_prefix,
    _resolve_checkout_path_prefix,
)


def _empty_text_result(query: str, normalized_prefix: str | None) -> dict[str, Any]:
    return {
        "query": query,
        "count": 0,
        "files_searched": 0,
        "items": [],
        "truncated": False,
        "scope": "checkout",
        "path_prefix": normalized_prefix,
    }


def _search_checkout_text(
    root: Path,
    query: str,
    *,
    limit: int,
    path_prefix: str | None = None,
) -> dict[str, Any]:
    """Search the current checkout directly from the filesystem."""
    query_value = query.strip()
    normalized_prefix, target_root = _resolve_checkout_path_prefix(root, path_prefix)
    if not query_value or (normalized_prefix and target_root is None):
        return _empty_text_result(query, normalized_prefix)

    all_checkout_files = _iter_checkout_files(root, start_root=target_root)
    if rg_result := _search_checkout_text_with_rg(root, query, query_value, normalized_prefix, limit, all_checkout_files):
        return rg_result
    return _search_checkout_text_with_python(root, query, query_value, normalized_prefix, limit, all_checkout_files)


def _search_checkout_text_with_rg(
    root: Path,
    query: str,
    query_value: str,
    normalized_prefix: str | None,
    limit: int,
    all_checkout_files: list[Path],
) -> dict[str, Any] | None:
    rg_path = shutil.which("rg")
    if not rg_path:
        return None
    args = [rg_path, "--line-number", "--ignore-case", "--fixed-strings", "--hidden"]
    for glob in CHECKOUT_EXCLUDE_GLOBS:
        args.extend(["--glob", glob])
    args.extend([query_value, normalized_prefix or "."])
    try:
        proc = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CHECKOUT_RIPGREP_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1):
        return None
    return _text_result_from_rg_output(root, query, normalized_prefix, limit, all_checkout_files, proc)


def _text_result_from_rg_output(
    root: Path,
    query: str,
    normalized_prefix: str | None,
    limit: int,
    all_checkout_files: list[Path],
    proc: subprocess.CompletedProcess[str],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    matched_files: set[str] = set()
    for raw_line in proc.stdout.splitlines():
        path_part, sep, remainder = raw_line.partition(":")
        if not sep:
            continue
        line_part, sep, content = remainder.partition(":")
        if not sep:
            continue
        rel_path = path_part[2:] if path_part.startswith("./") else path_part
        if not _path_matches_prefix(rel_path, normalized_prefix):
            continue
        try:
            line_number = int(line_part)
        except ValueError:
            continue
        matched_files.add(rel_path)
        if len(items) < limit:
            items.append(_text_item(rel_path, line_number, content, None))
    return _text_result(root, query, normalized_prefix, items, len(matched_files) or len(all_checkout_files), len(items) >= limit)


def _search_checkout_text_with_python(
    root: Path,
    query: str,
    query_value: str,
    normalized_prefix: str | None,
    limit: int,
    all_checkout_files: list[Path],
) -> dict[str, Any]:
    query_lower = query_value.lower()
    items: list[dict[str, Any]] = []
    files_searched = 0
    truncated = False
    for path in all_checkout_files:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        files_searched += 1
        rel_path = _normalize_rel_path(root, path)
        if rel_path is None or not _path_matches_prefix(rel_path, normalized_prefix):
            continue
        truncated = _append_python_text_matches(items, path, rel_path, content, query_lower, limit)
        if truncated:
            break
    return _text_result(root, query, normalized_prefix, items, files_searched, truncated, strategy="checkout_fallback")


def _append_python_text_matches(
    items: list[dict[str, Any]],
    path: Path,
    rel_path: str,
    content: str,
    query_lower: str,
    limit: int,
) -> bool:
    for line_number, line in enumerate(content.splitlines(), start=1):
        if query_lower not in line.lower():
            continue
        if len(items) >= limit:
            return True
        items.append(_text_item(rel_path, line_number, line, path.suffix.lower().lstrip(".")))
    return False


def _text_item(rel_path: str, line_number: int, content: str, language: str | None) -> dict[str, Any]:
    return {
        "path": rel_path,
        "line": line_number,
        "content": content[:LINE_PREVIEW_LIMIT],
        "language": language,
        "truncated_file": False,
    }


def _text_result(
    root: Path,
    query: str,
    normalized_prefix: str | None,
    items: list[dict[str, Any]],
    files_searched: int,
    truncated: bool,
    *,
    strategy: str = "checkout_ripgrep",
) -> dict[str, Any]:
    return {
        "query": query,
        "count": len(items),
        "files_searched": files_searched,
        "items": items,
        "truncated": truncated,
        "strategy": strategy,
        "scope": "checkout",
        "root_path": str(root),
        "path_prefix": normalized_prefix,
    }
