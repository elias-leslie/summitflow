"""File browser service helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

MAX_FILE_SIZE = 1_048_576
UPLOAD_CHUNK_SIZE = 1_048_576


@lru_cache(maxsize=1)
def _load_explorer_constants() -> tuple[frozenset[str], dict[str, str]]:
    from .explorer.constants import BINARY_EXTENSIONS, EXTENSION_TO_LANGUAGE

    return BINARY_EXTENSIONS, EXTENSION_TO_LANGUAGE


def resolve_safe_path(root_path: str | Path, relative_path: str) -> Path:
    """Resolve a relative path inside root_path and block only root escapes."""
    root = Path(root_path).resolve()
    target = (root / relative_path).resolve()
    target.relative_to(root)
    return target


def _entry_info(entry: Path, root: Path) -> dict[str, object]:
    """Build one directory entry payload."""
    rel_path = str(entry.relative_to(root))
    data: dict[str, object] = {
        'name': entry.name,
        'path': rel_path,
        'is_directory': entry.is_dir(),
    }
    if entry.is_dir():
        try:
            data['children_count'] = len(list(entry.iterdir()))
        except PermissionError:
            data['children_count'] = 0
    else:
        try:
            data['size'] = entry.stat().st_size
        except OSError:
            data['size'] = 0
        data['extension'] = entry.suffix.lower() if entry.suffix else None
    return data


def list_directory(root_path: str | Path, relative_path: str = '') -> dict[str, object]:
    """List directory entries under root_path without name-based hiding."""
    target = resolve_safe_path(root_path, relative_path)
    if not target.is_dir():
        msg = f'Not a directory: {relative_path}'
        raise FileNotFoundError(msg)

    root = Path(root_path).resolve()
    entries = [
        _entry_info(entry, root)
        for entry in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    ]
    return {'entries': entries, 'path': relative_path or '', 'total': len(entries)}


def _detect_language(name: str, extension: str) -> str | None:
    """Return CodeMirror language id for a filename."""
    _, extension_to_language = _load_explorer_constants()
    language = extension_to_language.get(extension)
    if not language and name.lower() in {'dockerfile', 'containerfile'}:
        return 'dockerfile'
    return language


def _read_text_content(target: Path, truncated: bool) -> str:
    """Read text content from a file."""
    try:
        with target.open(encoding='utf-8', errors='replace') as handle:
            return handle.read(MAX_FILE_SIZE) if truncated else handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        msg = f'Cannot read file: {exc}'
        raise ValueError(msg) from exc


def read_file(root_path: str | Path, relative_path: str) -> dict[str, object]:
    """Read file content with binary detection and size limits."""
    target = resolve_safe_path(root_path, relative_path)
    if not target.is_file():
        msg = f'Not a file: {relative_path}'
        raise FileNotFoundError(msg)

    stat = target.stat()
    extension = target.suffix.lower()
    base: dict[str, object] = {
        'path': relative_path,
        'name': target.name,
        'size': stat.st_size,
        'extension': extension or None,
        'truncated': False,
    }

    if _is_binary(target, extension):
        return {**base, 'content': None, 'lines': 0, 'is_binary': True, 'language': None}

    truncated = stat.st_size > MAX_FILE_SIZE
    content = _read_text_content(target, truncated)
    lines = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
    return {
        **base,
        'content': content,
        'lines': lines,
        'is_binary': False,
        'language': _detect_language(target.name, extension),
        'truncated': truncated,
    }


def _is_binary(path: Path, extension: str) -> bool:
    """Check if a file is binary using extension and content sampling."""
    binary_extensions, _ = _load_explorer_constants()
    if extension in binary_extensions:
        return True
    try:
        with path.open('rb') as handle:
            return b'\x00' in handle.read(8192)
    except OSError:
        return True


def get_download_target(root_path: str | Path, relative_path: str) -> Path:
    """Return a validated file path for download streaming."""
    target = resolve_safe_path(root_path, relative_path)
    if not target.is_file():
        msg = f'Not a file: {relative_path}'
        raise FileNotFoundError(msg)
    return target


def write_uploaded_file(
    root_path: str | Path,
    relative_dir: str,
    filename: str | None,
    source: BinaryIO,
) -> dict[str, object]:
    """Write uploaded content into a validated directory."""
    directory = resolve_safe_path(root_path, relative_dir)
    if not directory.is_dir():
        msg = f'Not a directory: {relative_dir}'
        raise FileNotFoundError(msg)

    safe_name = _normalize_upload_name(filename)
    target = directory / safe_name
    if target.exists():
        msg = f'File already exists: {target.name}'
        raise FileExistsError(msg)

    with target.open('wb') as handle:
        while True:
            chunk = source.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            handle.write(chunk)

    rel_path = str(target.relative_to(Path(root_path).resolve()))
    return {
        'path': rel_path,
        'directory': relative_dir or '',
        'name': safe_name,
        'size': target.stat().st_size,
    }


def _normalize_upload_name(filename: str | None) -> str:
    raw_name = (filename or '').strip()
    if not raw_name:
        raise ValueError('Upload filename is required')

    candidate = Path(raw_name)
    if candidate.name != raw_name or raw_name in {'.', '..'}:
        raise ValueError('Upload filename must not include directories')

    return raw_name
