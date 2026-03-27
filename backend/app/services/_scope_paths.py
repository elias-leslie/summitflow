"""Shared scope-path normalization helpers."""

from __future__ import annotations

from pathlib import PurePosixPath


def normalize_single_scope_path(raw: object) -> str | None:
    """Normalize a single path value, returning None if invalid."""
    if not isinstance(raw, str):
        return None
    path = raw.strip()
    while path.startswith("./"):
        path = path[2:]
    if not path or path.startswith("/"):
        return None
    if "\\" in path or "//" in path or path.endswith("/"):
        return None
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    normalized = str(PurePosixPath(path))
    return normalized if normalized != "." and not normalized.endswith("/") else None


def normalize_scope_values(values: object) -> frozenset[str]:
    """Normalize a list of path strings into a clean frozenset."""
    if not isinstance(values, list):
        return frozenset()
    result: set[str] = set()
    for raw in values:
        normalized = normalize_single_scope_path(raw)
        if normalized:
            result.add(normalized)
    return frozenset(result)
