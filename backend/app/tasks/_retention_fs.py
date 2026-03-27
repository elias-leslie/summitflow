"""Filesystem utilities for host retention cleanup."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict


class CleanupResult(TypedDict):
    deleted_paths: int
    bytes_reclaimed: int
    deleted: list[str]


def path_size_bytes(path: Path) -> int:
    """Return approximate on-disk size of a path without following symlinks."""
    try:
        if path.is_symlink() or path.is_file():
            return int(path.lstat().st_size)
    except OSError:
        return 0

    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        for name in dirs:
            dir_path = root_path / name
            try:
                if dir_path.is_symlink():
                    total += int(dir_path.lstat().st_size)
            except OSError:
                continue
        for name in files:
            file_path = root_path / name
            try:
                total += int(file_path.lstat().st_size)
            except OSError:
                continue
    return total


def delete_path(path: Path) -> int:
    """Delete a path and return the bytes that were reclaimed."""
    reclaimed = path_size_bytes(path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
        return reclaimed
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return 0
    return reclaimed


def age_hours(path: Path, *, now: datetime) -> float:
    """Return how many hours ago a path was last modified."""
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return 0.0
    return max((now - modified).total_seconds() / 3600.0, 0.0)


def cleanup_old_children(
    root: Path,
    *,
    max_age_hours: int,
    now: datetime,
) -> CleanupResult:
    """Delete children of root that exceed max_age_hours and return a summary."""
    if not root.is_dir():
        return CleanupResult(deleted_paths=0, bytes_reclaimed=0, deleted=[])

    deleted: list[str] = []
    reclaimed = 0
    for child in root.iterdir():
        if age_hours(child, now=now) < max_age_hours:
            continue
        reclaimed += delete_path(child)
        deleted.append(str(child))
    return CleanupResult(deleted_paths=len(deleted), bytes_reclaimed=reclaimed, deleted=deleted)


def collect_legacy_review_candidates(
    home_dir: Path,
    *,
    max_age_hours: int,
    now: datetime,
) -> list[dict[str, str | float | int]]:
    """Return metadata for legacy project roots that exceed max_age_hours."""
    root = home_dir / "_legacy-project-roots"
    if not root.is_dir():
        return []

    candidates: list[dict[str, str | float | int]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        child_age = age_hours(child, now=now)
        if child_age < max_age_hours:
            continue
        candidates.append(
            {
                "path": str(child),
                "reason": "legacy_project_root",
                "age_hours": round(child_age, 1),
                "size_bytes": path_size_bytes(child),
                "action": "review_only",
            }
        )
    return candidates
