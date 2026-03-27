"""Internal helpers for autosnapshot — manifest I/O and scope discovery utilities.

These are implementation details of autosnapshot.py; do not import directly.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from .quick_snapshots import (
    QuickSnapshot,
    SnapshotScope,
)


def load_manifest_entries(manifest_path: Path) -> list[QuickSnapshot] | None:
    """Parse a manifest.json, returning entries or None on any error (including missing file)."""
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        return [
            QuickSnapshot.from_dict(item)
            for item in json.loads(raw)
            if isinstance(item, dict)
        ]
    except Exception:
        return None


def iter_archived_manifest_scopes(
    root: Path,
) -> Iterator[tuple[Path, str, SnapshotScope]]:
    """Yield (scope_dir, project_id, scope) for each readable manifest under root."""
    if not root.is_dir():
        return
    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        for scope_dir in sorted(project_dir.iterdir()):
            entries = load_manifest_entries(scope_dir / "manifest.json")
            if not entries:
                continue
            latest = max(entries, key=lambda e: e.created_at)
            yield scope_dir, latest.project_id, SnapshotScope(
                latest.scope_type, latest.scope_name, Path(latest.worktree_path)
            )


def find_manifest_scope_dir(
    project_id: str,
    scope: SnapshotScope,
    scope_key: str,
) -> Path | None:
    snaps_root = Path.home() / ".local" / "share" / "st" / "snaps"
    return next(
        (
            sd
            for sd, pid, s in iter_archived_manifest_scopes(snaps_root)
            if f"{pid}/{s.scope_type}:{s.scope_name}" == scope_key
        ),
        None,
    )


def lane_scopes_for_project(
    project_dir: Path, project_id: str
) -> list[tuple[str, SnapshotScope]]:
    """Return (project_id, scope) pairs for lane dirs containing a .git entry."""
    return [
        (project_id, SnapshotScope("lane", lane_dir.name, lane_dir.resolve()))
        for lane_dir in sorted(project_dir.iterdir())
        if lane_dir.is_dir() and (lane_dir / ".git").exists()
    ]
