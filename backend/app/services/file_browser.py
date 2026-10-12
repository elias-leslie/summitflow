"""File browser service helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

from ..utils import safe_subprocess
from ..utils.shared_paths import get_workspaces_root

MAX_FILE_SIZE = 1_048_576
UPLOAD_CHUNK_SIZE = 1_048_576


@lru_cache(maxsize=1)
def _load_explorer_constants() -> tuple[frozenset[str], dict[str, str]]:
    from .explorer.constants import BINARY_EXTENSIONS, EXTENSION_TO_LANGUAGE

    return BINARY_EXTENSIONS, EXTENSION_TO_LANGUAGE


def _root_prefix(root: str) -> str:
    return root if root.endswith(os.sep) else root + os.sep


def resolve_safe_path(root_path: str | Path, relative_path: str) -> Path:
    """Resolve a path inside root_path, following symlinks, and reject root escapes.

    The containment check runs on the fully resolved path, so '..' segments,
    absolute paths and symlinks that point outside the root all raise ValueError.
    """
    root = os.path.realpath(root_path)
    target = os.path.realpath(os.path.join(root, relative_path))
    if target == root:
        return Path(root)
    if not target.startswith(_root_prefix(root)):
        msg = f'Path escapes browse root: {relative_path}'
        raise ValueError(msg)
    return Path(target)


def _sibling_in_root(root_path: str | Path, target: Path, name: str) -> Path:
    """Return target's sibling called name, confined to root_path without following it."""
    root = os.path.realpath(root_path)
    sibling = os.path.normpath(os.path.join(str(target.parent), name))
    if not sibling.startswith(_root_prefix(root)):
        msg = f'Path escapes browse root: {name}'
        raise ValueError(msg)
    return Path(sibling)


def _display_path(path: Path, root: Path, absolute_paths: bool) -> str:
    if absolute_paths:
        return str(path)
    if path == root:
        return ''
    return str(path.relative_to(root))


def _entry_info(entry: Path, root: Path, *, absolute_paths: bool = False) -> dict[str, object]:
    """Build one directory entry payload."""
    data: dict[str, object] = {
        'name': entry.name,
        'path': _display_path(entry, root, absolute_paths),
        'absolute_path': str(entry),
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


def list_directory(
    root_path: str | Path,
    relative_path: str = '',
    *,
    absolute_paths: bool = False,
) -> dict[str, object]:
    """List directory entries under root_path without name-based hiding."""
    target = resolve_safe_path(root_path, relative_path)
    if not target.is_dir():
        msg = f'Not a directory: {relative_path}'
        raise FileNotFoundError(msg)

    root = Path(root_path).resolve()
    entries = [
        _entry_info(entry, root, absolute_paths=absolute_paths)
        for entry in sorted(
            target.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )
    ]
    return {
        'entries': entries,
        'path': _display_path(target, root, absolute_paths),
        'absolute_path': str(target),
        'total': len(entries),
    }


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
    *,
    absolute_paths: bool = False,
) -> dict[str, object]:
    """Write uploaded content into a validated directory."""
    directory = resolve_safe_path(root_path, relative_dir)
    if not directory.is_dir():
        msg = f'Not a directory: {relative_dir}'
        raise FileNotFoundError(msg)

    safe_name = _normalize_upload_name(filename)
    target = directory / safe_name
    resolved_target = resolve_safe_path(root_path, str(target))
    if resolved_target.exists() and not resolved_target.is_file():
        msg = f'Upload target is not a file: {target.name}'
        raise IsADirectoryError(msg)

    with resolved_target.open('wb') as handle:
        while True:
            chunk = source.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            handle.write(chunk)

    root = Path(root_path).resolve()
    return {
        'path': _display_path(target, root, absolute_paths),
        'directory': _display_path(directory, root, absolute_paths),
        'name': safe_name,
        'size': resolved_target.stat().st_size,
    }


def create_directory(
    root_path: str | Path,
    relative_dir: str,
    name: str,
    *,
    absolute_paths: bool = False,
) -> dict[str, object]:
    """Create a directory inside a validated directory."""
    directory = resolve_safe_path(root_path, relative_dir)
    if not directory.is_dir():
        msg = f'Not a directory: {relative_dir}'
        raise FileNotFoundError(msg)

    safe_name = _normalize_upload_name(name)
    target = directory / safe_name
    target.mkdir()
    return _entry_info(target, Path(root_path).resolve(), absolute_paths=absolute_paths)


def write_text_file(
    root_path: str | Path,
    relative_path: str,
    content: str,
    *,
    create: bool = False,
    absolute_paths: bool = False,
) -> dict[str, object]:
    """Create or replace UTF-8 text content at a validated file path."""
    target = resolve_safe_path(root_path, relative_path)
    if create and target.exists():
        msg = f'File already exists: {target.name}'
        raise FileExistsError(msg)
    if not create and not target.is_file():
        msg = f'Not a file: {relative_path}'
        raise FileNotFoundError(msg)
    if target.exists() and not target.is_file():
        msg = f'Not a file: {relative_path}'
        raise IsADirectoryError(msg)
    if not target.parent.is_dir():
        msg = f'Not a directory: {target.parent}'
        raise FileNotFoundError(msg)

    target.write_text(content, encoding='utf-8')
    stat = target.stat()
    root = Path(root_path).resolve()
    return {
        'path': _display_path(target, root, absolute_paths),
        'name': target.name,
        'size': stat.st_size,
        'extension': target.suffix.lower() if target.suffix else None,
    }


def create_text_file(
    root_path: str | Path,
    relative_dir: str,
    name: str,
    content: str,
    *,
    absolute_paths: bool = False,
) -> dict[str, object]:
    """Create a UTF-8 text file inside a validated directory."""
    directory = resolve_safe_path(root_path, relative_dir)
    if not directory.is_dir():
        msg = f'Not a directory: {relative_dir}'
        raise FileNotFoundError(msg)

    safe_name = _normalize_upload_name(name)
    root = Path(root_path).resolve()
    path = _display_path(directory / safe_name, root, absolute_paths)
    return write_text_file(
        root_path,
        path,
        content,
        create=True,
        absolute_paths=absolute_paths,
    )


def delete_path(root_path: str | Path, relative_path: str) -> dict[str, object]:
    """Delete a validated file or directory path."""
    target = resolve_safe_path(root_path, relative_path)
    root = Path(root_path).resolve()
    if target == root:
        raise ValueError('Cannot delete browse root')
    if not target.exists():
        msg = f'Path not found: {relative_path}'
        raise FileNotFoundError(msg)
    _guard_destructive_delete(target)

    is_directory = target.is_dir()
    if is_directory:
        shutil.rmtree(target)
    else:
        target.unlink()
    return {'path': relative_path, 'deleted': True, 'is_directory': is_directory}


def _git_toplevel(directory: Path) -> Path | None:
    try:
        result = safe_subprocess.run(
            ['git', '-C', str(directory), 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    toplevel = result.stdout.strip()
    return Path(toplevel).resolve() if toplevel else None


def _guard_destructive_delete(target: Path) -> None:
    """Refuse deletes outside managed workspaces or over another live session's paths."""
    workspaces_root = get_workspaces_root().resolve()
    if workspaces_root not in target.parents:
        msg = f'Refusing to delete outside the managed workspaces root: {target}'
        raise PermissionError(msg)
    if target.is_dir() and (target / '.git').exists():
        msg = f'Refusing to delete a git checkout root: {target}'
        raise PermissionError(msg)

    repo_root = _git_toplevel(target.parent)
    if repo_root is None:
        return
    from . import destructive_path_guard

    relative = target.relative_to(repo_root).as_posix()
    try:
        decision = destructive_path_guard.check_destructive_paths(repo_root, [relative])
    except destructive_path_guard.DestructivePathGuardError as exc:
        raise PermissionError(str(exc)) from exc
    if decision.blocked:
        raise PermissionError(destructive_path_guard.format_guard_report(decision))


def rename_path(
    root_path: str | Path,
    relative_path: str,
    name: str,
    *,
    absolute_paths: bool = False,
) -> dict[str, object]:
    """Rename a validated path without moving it to another directory."""
    target = resolve_safe_path(root_path, relative_path)
    root = Path(root_path).resolve()
    if target == root:
        raise ValueError('Cannot rename browse root')
    if not target.exists():
        msg = f'Path not found: {relative_path}'
        raise FileNotFoundError(msg)

    safe_name = _normalize_upload_name(name)
    destination = _sibling_in_root(root_path, target, safe_name)
    if destination.exists():
        msg = f'Path already exists: {safe_name}'
        raise FileExistsError(msg)

    renamed = target.rename(destination)
    return _entry_info(renamed, root, absolute_paths=absolute_paths)


def _normalize_upload_name(filename: str | None) -> str:
    raw_name = (filename or '').strip()
    if not raw_name:
        raise ValueError('Upload filename is required')

    candidate = Path(raw_name)
    if candidate.name != raw_name or raw_name in {'.', '..'}:
        raise ValueError('Upload filename must not include directories')

    return raw_name
