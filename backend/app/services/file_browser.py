"""File browser service — path security, directory listing, file reading.

Provides safe filesystem browsing for the file explorer UI.
Uses SKIP_DIRS from explorer constants for consistent directory filtering.
"""

from __future__ import annotations

from pathlib import Path

from .explorer.constants import (
    BINARY_EXTENSIONS,
    EXTENSION_TO_LANGUAGE,
    FORBIDDEN_DIRS,
    SKIP_DIRS,
)

# Maximum file size to read (1 MB)
MAX_FILE_SIZE = 1_048_576


def resolve_safe_path(root_path: str, relative_path: str) -> Path:
    """Resolve a relative path within root_path, preventing path traversal.

    Raises ValueError if path escapes root; PermissionError for forbidden dirs.
    """
    root = Path(root_path).resolve()
    target = (root / relative_path).resolve()
    target.relative_to(root)  # raises ValueError if outside root
    for part in Path(relative_path).parts:
        if part in FORBIDDEN_DIRS:
            msg = f"Access denied: {part}"
            raise PermissionError(msg)
    return target


def _entry_info(entry: Path, root: Path) -> dict:
    """Build a single directory-entry dict for list_directory."""
    rel_path = str(entry.relative_to(root))
    data: dict = {"name": entry.name, "path": rel_path, "is_directory": entry.is_dir()}
    if entry.is_dir():
        try:
            children = [
                c for c in entry.iterdir()
                if not (c.name.startswith(".") and c.is_dir())
                and not (c.is_dir() and c.name in SKIP_DIRS)
            ]
            data["children_count"] = len(children)
        except PermissionError:
            data["children_count"] = 0
    else:
        try:
            data["size"] = entry.stat().st_size
        except OSError:
            data["size"] = 0
        data["extension"] = entry.suffix.lower() if entry.suffix else None
    return data


def list_directory(root_path: str, relative_path: str = "") -> dict:
    """List directory entries (dirs-first, alphabetical), filtering SKIP_DIRS and hidden dirs."""
    target = resolve_safe_path(root_path, relative_path)
    if not target.is_dir():
        msg = f"Not a directory: {relative_path}"
        raise FileNotFoundError(msg)

    root = Path(root_path).resolve()
    entries = []
    for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        if entry.name.startswith(".") and entry.is_dir():
            continue
        if entry.is_dir() and entry.name in SKIP_DIRS:
            continue
        entries.append(_entry_info(entry, root))

    return {"entries": entries, "path": relative_path or "", "total": len(entries)}


def _detect_language(name: str, extension: str) -> str | None:
    """Return CodeMirror language ID for a filename/extension pair."""
    lang = EXTENSION_TO_LANGUAGE.get(extension)
    if not lang and name.lower() in ("dockerfile", "containerfile"):
        return "dockerfile"
    return lang


def _read_text_content(target: Path, truncated: bool) -> str:
    """Read text content from a file, respecting MAX_FILE_SIZE."""
    try:
        with open(target, encoding="utf-8", errors="replace") as f:
            return f.read(MAX_FILE_SIZE) if truncated else f.read()
    except (OSError, UnicodeDecodeError) as e:
        msg = f"Cannot read file: {e}"
        raise ValueError(msg) from e


def read_file(root_path: str, relative_path: str) -> dict:
    """Read file content with binary detection and size limits."""
    target = resolve_safe_path(root_path, relative_path)
    if not target.is_file():
        msg = f"Not a file: {relative_path}"
        raise FileNotFoundError(msg)

    stat = target.stat()
    extension = target.suffix.lower()
    base: dict = {
        "path": relative_path, "name": target.name, "size": stat.st_size,
        "extension": extension or None, "truncated": False,
    }

    if _is_binary(target, extension):
        return {**base, "content": None, "lines": 0, "is_binary": True, "language": None}

    truncated = stat.st_size > MAX_FILE_SIZE
    content = _read_text_content(target, truncated)
    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return {
        **base, "content": content, "lines": lines, "is_binary": False,
        "language": _detect_language(target.name, extension), "truncated": truncated,
    }


def _is_binary(path: Path, extension: str) -> bool:
    """Check if a file is binary using extension and content sampling.

    Two-step detection:
    1. Known binary extensions (images, executables, archives, fonts, etc.)
    2. Content sampling — null byte in the first 8 KB reliably indicates binary.

    MIME-type heuristics were removed because Python's mimetypes module
    returns non-text MIME types for many text formats (.sql → application/sql,
    .yaml → application/yaml, .rb → application/x-ruby, etc.), causing
    false positives.
    """
    if extension in BINARY_EXTENSIONS:
        return True
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(8192)
    except OSError:
        return True
