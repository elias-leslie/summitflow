"""Manifest persistence, path resolution, and snapshot metadata helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..workspace_paths import get_workspace_snapshots_base_dir
from ._helpers import _sanitize_label
from ._models import QuickSnapshot, SnapshotError, SnapshotScope


def _scope_key(scope: SnapshotScope) -> str:
    return f"{scope.scope_type}-{_sanitize_label(scope.scope_name)}"


def _manifest_dir(project_id: str, scope: SnapshotScope) -> Path:
    target = Path.home() / ".local" / "share" / "st" / "snaps" / project_id / _scope_key(scope)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _manifest_path(project_id: str, scope: SnapshotScope) -> Path:
    return _manifest_dir(project_id, scope) / "manifest.json"


def _artifacts_dir(project_id: str, scope: SnapshotScope, snapshot_id: str) -> Path:
    target = _manifest_dir(project_id, scope) / "artifacts" / snapshot_id
    target.mkdir(parents=True, exist_ok=True)
    return target


def _load_manifest(project_id: str, scope: SnapshotScope) -> list[QuickSnapshot]:
    path = _manifest_path(project_id, scope)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"Snapshot manifest is invalid: {path}") from exc
    if not isinstance(raw, list):
        raise SnapshotError(f"Snapshot manifest has unexpected format: {path}")
    entries = [QuickSnapshot.from_dict(item) for item in raw if isinstance(item, dict)]
    entries.sort(key=lambda entry: entry.created_at, reverse=True)
    return entries


def _save_manifest(project_id: str, scope: SnapshotScope, entries: list[QuickSnapshot]) -> None:
    path = _manifest_path(project_id, scope)
    ordered = sorted(entries, key=lambda entry: entry.created_at, reverse=True)
    path.write_text(
        json.dumps([entry.to_dict() for entry in ordered], indent=2),
        encoding="utf-8",
    )


def _snapshot_destination(project_id: str, scope: SnapshotScope, snapshot_id: str) -> Path:
    root = get_workspace_snapshots_base_dir(project_id) / f"{scope.scope_type}s" / _sanitize_label(
        scope.scope_name
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / snapshot_id


def _copy_index_artifact(
    *,
    git_dir: Path,
    project_id: str,
    scope: SnapshotScope,
    snapshot_id: str,
) -> str | None:
    index_path = git_dir / "index"
    if not index_path.exists():
        return None
    artifact_path = _artifacts_dir(project_id, scope, snapshot_id) / "index"
    shutil.copy2(index_path, artifact_path)
    return str(artifact_path)


def _snapshot_manifest_root(project_id: str) -> Path:
    return Path.home() / ".local" / "share" / "st" / "snaps" / project_id


def _recovery_name(name: str | None, snapshot: QuickSnapshot) -> str:
    if name:
        return _sanitize_label(name)
    stem = snapshot.name or snapshot.id
    return _sanitize_label(f"recover-{stem}")[:80]


def _recovery_branch_name(snapshot: QuickSnapshot, recovery_name: str) -> str:
    seed = snapshot.scope_name if snapshot.scope_type == "lane" else snapshot.project_id
    return _sanitize_label(f"recover/{seed}/{recovery_name}")[:120]


def _rsync_snapshot_contents(snapshot_path: Path, destination: Path) -> None:
    try:
        subprocess.run(
            [
                "rsync",
                "-a",
                "--delete",
                "--exclude=.git",
                f"{snapshot_path}/",
                f"{destination}/",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or str(exc)
        raise SnapshotError(f"Failed to sync recovered snapshot contents:\n{stderr}") from exc
    except OSError as exc:
        raise SnapshotError(f"Failed to run rsync for snapshot recovery: {exc}") from exc


def _update_manifest_entries(
    entries: list[QuickSnapshot],
    snapshot: QuickSnapshot,
    project_id: str,
    scope: SnapshotScope,
    **updates: str | None,
) -> QuickSnapshot:
    """Update the matching manifest entry with *updates* and persist."""
    updated: list[QuickSnapshot] = []
    result = snapshot
    for entry in entries:
        if entry.id == snapshot.id:
            entry = QuickSnapshot.from_dict({**entry.to_dict(), **updates})
            result = entry
        updated.append(entry)
    _save_manifest(project_id, scope, updated)
    return result
