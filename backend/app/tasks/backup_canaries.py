"""Nightshift canary files never enter a backup.

Decoy files (``nightshift canary list``) alert when used, so captures skip
them by path before any stat, open or copy. Only the paths are read. The last
good list is kept so a transient Nightshift CLI failure does not drop the
protection; with no list at all, sources under the home directory fail closed.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from pathlib import Path

from ..services.backup_keys import backup_key_directory

_TIMEOUT = 30


def _cache_path() -> Path:
    return backup_key_directory().parent / "canary-paths.json"


def _nightshift() -> str | None:
    found = shutil.which("nightshift")
    fallback = Path.home() / ".local" / "bin" / "nightshift"
    return found or (str(fallback) if fallback.is_file() else None)


def _file_path(entry: str) -> Path | None:
    """Map a registry path such as ``~/.aws/credentials [prod-archive]`` to its file.

    Entries that are not file paths (hosts, repository content descriptions)
    are ignored; a suffix naming a section inside the file is dropped.
    """
    if not entry.startswith(("~/", "/")):
        return None
    candidate = os.path.expanduser(entry)
    while True:
        if os.path.lexists(candidate):
            return Path(candidate)
        if " " not in candidate:
            return None
        candidate = candidate.rsplit(" ", 1)[0]


def _registry() -> list[str] | None:
    binary = _nightshift()
    if binary is None:
        return None
    try:
        result = subprocess.run([binary, "canary", "list"], capture_output=True, text=True, timeout=_TIMEOUT, check=False)
        entries = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not isinstance(entries, list):
        return None
    return [str(item["path"]) for item in entries if isinstance(item, dict) and item.get("path")]


def canary_paths() -> list[Path] | None:
    """Return existing canary files, or None when no list has ever loaded."""
    cache = _cache_path()
    entries = _registry()
    if entries is not None:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(entries))
        except OSError:
            pass
    else:
        try:
            entries = json.loads(cache.read_text())
        except (OSError, ValueError):
            return None
    return [path for path in (_file_path(entry) for entry in entries) if path is not None]


def canary_excludes(source: Path) -> tuple[str, ...]:
    """Exact exclude patterns for canaries inside ``source``."""
    paths = canary_paths()
    root = Path(os.path.abspath(source))
    if paths is None:
        if root.is_relative_to(Path.home()) or Path.home().is_relative_to(root):
            raise RuntimeError("Nightshift canary list unavailable; capture under the home directory refused")
        return ()
    excludes = []
    for path in paths:
        absolute = Path(os.path.abspath(path))
        if root == absolute:
            raise RuntimeError("Backup source is a Nightshift canary")
        if absolute.is_relative_to(root):
            excludes.append("./" + glob.escape(absolute.relative_to(root).as_posix()))
    return tuple(excludes)
