"""File browser service — path security, directory listing, file reading.

Provides safe filesystem browsing for the file explorer UI.
Uses SKIP_DIRS from explorer constants for consistent directory filtering.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from .explorer.constants import SKIP_DIRS

# Maximum file size to read (1 MB)
MAX_FILE_SIZE = 1_048_576

# Extensions known to be binary
BINARY_EXTENSIONS = frozenset(
    {
        ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin",
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
        ".woff", ".woff2", ".ttf", ".eot",
        ".mp3", ".mp4", ".wav", ".ogg", ".webm",
        ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
        ".lock", ".sqlite", ".db",
    }
)

# Map file extensions to CodeMirror language identifiers
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".md": "markdown",
    ".mdx": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sql": "sql",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".cpp": "cpp",
    ".c": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".xml": "xml",
    ".php": "php",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".toml": "toml",
    ".dockerfile": "dockerfile",
}

# Sensitive directories that should never be browsed
FORBIDDEN_DIRS = frozenset({".git", ".env"})


def resolve_safe_path(root_path: str, relative_path: str) -> Path:
    """Resolve a relative path within root_path, preventing traversal attacks.

    Uses Path.resolve() to canonicalize, then relative_to() to enforce containment.
    Also blocks SKIP_DIRS components for defense-in-depth.

    Args:
        root_path: Project root directory (absolute)
        relative_path: User-provided relative path

    Returns:
        Resolved absolute Path within root

    Raises:
        ValueError: If path escapes root or contains forbidden components
    """
    root = Path(root_path).resolve()
    # Normalize and join
    target = (root / relative_path).resolve()

    # Enforce containment — raises ValueError if target is outside root
    target.relative_to(root)

    # Block forbidden directories (security-sensitive)
    for part in Path(relative_path).parts:
        if part in FORBIDDEN_DIRS:
            msg = f"Access denied: {part}"
            raise PermissionError(msg)

    return target


def list_directory(root_path: str, relative_path: str = "") -> dict:
    """List directory entries, sorted dirs-first then alphabetically.

    Filters SKIP_DIRS and hidden directories for clean browsing.

    Args:
        root_path: Project root directory
        relative_path: Path relative to root (empty string = root)

    Returns:
        Dict with entries, path, and total count
    """
    target = resolve_safe_path(root_path, relative_path)

    if not target.is_dir():
        msg = f"Not a directory: {relative_path}"
        raise FileNotFoundError(msg)

    entries = []
    for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        name = entry.name

        # Skip hidden files/dirs (except root-level dotfiles like .env.example)
        if name.startswith(".") and entry.is_dir():
            continue

        # Skip filtered directories
        if entry.is_dir() and name in SKIP_DIRS:
            continue

        rel_path = str(entry.relative_to(Path(root_path).resolve()))

        entry_data: dict = {
            "name": name,
            "path": rel_path,
            "is_directory": entry.is_dir(),
        }

        if entry.is_dir():
            try:
                children = [
                    c for c in entry.iterdir()
                    if not (c.name.startswith(".") and c.is_dir())
                    and not (c.is_dir() and c.name in SKIP_DIRS)
                ]
                entry_data["children_count"] = len(children)
            except PermissionError:
                entry_data["children_count"] = 0
        else:
            try:
                stat = entry.stat()
                entry_data["size"] = stat.st_size
            except OSError:
                entry_data["size"] = 0
            entry_data["extension"] = entry.suffix.lower() if entry.suffix else None

        entries.append(entry_data)

    return {
        "entries": entries,
        "path": relative_path or "",
        "total": len(entries),
    }


def read_file(root_path: str, relative_path: str) -> dict:
    """Read file content with binary detection and size limits.

    Args:
        root_path: Project root directory
        relative_path: Path relative to root

    Returns:
        Dict with file content, metadata, and language info
    """
    target = resolve_safe_path(root_path, relative_path)

    if not target.is_file():
        msg = f"Not a file: {relative_path}"
        raise FileNotFoundError(msg)

    stat = target.stat()
    extension = target.suffix.lower()
    name = target.name

    # Detect binary files
    is_binary = _is_binary(target, extension)

    if is_binary:
        return {
            "path": relative_path,
            "name": name,
            "content": None,
            "size": stat.st_size,
            "lines": 0,
            "extension": extension or None,
            "is_binary": True,
            "language": None,
            "truncated": False,
        }

    # Read text content with size limit
    truncated = stat.st_size > MAX_FILE_SIZE
    try:
        with open(target, encoding="utf-8", errors="replace") as f:
            content = f.read(MAX_FILE_SIZE) if truncated else f.read()
    except (OSError, UnicodeDecodeError) as e:
        msg = f"Cannot read file: {e}"
        raise ValueError(msg) from e

    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    language = EXTENSION_TO_LANGUAGE.get(extension)

    # Special case: Dockerfile without extension
    if not language and name.lower() in ("dockerfile", "containerfile"):
        language = "dockerfile"

    return {
        "path": relative_path,
        "name": name,
        "content": content,
        "size": stat.st_size,
        "lines": lines,
        "extension": extension or None,
        "is_binary": False,
        "language": language,
        "truncated": truncated,
    }


def _is_binary(path: Path, extension: str) -> bool:
    """Check if a file is binary using extension, MIME type, and content sampling."""
    # Check extension
    if extension in BINARY_EXTENSIONS:
        return True

    # Check MIME type
    mime_type, _ = mimetypes.guess_type(str(path))
    if (
        mime_type
        and not mime_type.startswith(("text/", "application/json", "application/xml"))
        and mime_type not in ("application/javascript", "application/typescript")
    ):
        return True

    # Check for null bytes in first 8KB
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
            if b"\x00" in chunk:
                return True
    except OSError:
        return True

    return False
