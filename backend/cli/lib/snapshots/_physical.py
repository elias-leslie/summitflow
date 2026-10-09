"""Shared physical-point coordination and nonrecursive boundary inventory."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from ._helpers import _git
from ._models import QuickSnapshot, SnapshotError
from ._saved_work import _DISPOSABLE, beneath, classifications


@contextlib.contextmanager
def physical_lock() -> Iterator[None]:
    root = Path.home() / ".local/share/st/snaps"
    root.mkdir(parents=True, exist_ok=True)
    with (root / "physical.lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SnapshotError("Deferred: shared physical snapshot operation in progress") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def all_entries() -> list[QuickSnapshot]:
    entries = []
    for path in (Path.home() / ".local/share/st/snaps").glob("*/*/manifest.json"):
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, list):
                raise ValueError("manifest must be an entry list")
            entries.extend(QuickSnapshot.from_dict(item) for item in data)
        except Exception as exc:
            raise SnapshotError(f"Cannot verify shared snapshot references: {path}: {exc}") from exc
    return entries


def latest_physical_point(boundary: Path) -> QuickSnapshot | None:
    candidates = [entry for entry in all_entries() if entry.capture_root == str(boundary) and Path(entry.snapshot_path).exists()]
    return max(candidates, key=lambda entry: entry.created_at) if candidates else None


def recent(point: QuickSnapshot, minutes: int = 15) -> bool:
    created = datetime.fromisoformat(point.created_at)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (datetime.now(UTC) - created).total_seconds() < minutes * 60


def referenced_elsewhere(point: QuickSnapshot) -> bool:
    return any(entry.snapshot_path == point.snapshot_path and (entry.project_id, entry.scope_path, entry.id) != (point.project_id, point.scope_path, point.id) for entry in all_entries())


def inventory_nested(boundary: Path, *, project: Path | None = None) -> list[str]:
    """Inspect actual inode/device boundaries; never descend into nested subvolumes."""
    nested = []
    device = boundary.stat().st_dev
    tracked = _git(project, ["ls-files", "-z"]).stdout.split("\0") if project else []
    def denied(error):
        raise SnapshotError(f"Cannot inventory Btrfs boundaries: {error}") from error
    for current, dirs, _ in os.walk(boundary, followlinks=False, onerror=denied):
        current_path = Path(current)
        rules = classifications(current_path) if (current_path / "project.identity.json").is_file() else {"durable_data": [], "disposable_outputs": []}
        for directory in list(dirs):
            child = current_path / directory
            # Host-managed backup metadata is private and outside project
            # source. Do not traverse it while inventorying a shared boundary.
            if (child == Path("/srv/workspaces/.btrbk") and project is not None
                    and child != project and child not in project.parents
                    and project not in child.parents):
                dirs.remove(directory)
                continue
            if child.is_symlink():
                dirs.remove(directory)
                continue
            metadata = child.stat()
            if metadata.st_ino == 256 or metadata.st_dev != device:
                nested.append(child.relative_to(boundary).as_posix())
                dirs.remove(directory)
            elif directory in _DISPOSABLE or beneath(directory, rules["durable_data"] + rules["disposable_outputs"]):
                relative = child.relative_to(project).as_posix() if project and project in child.parents else None
                if relative is None or not any(path.startswith(relative + "/") for path in tracked):
                    dirs.remove(directory)
    return sorted(nested)


def require_complete_project(boundary: Path, project: Path, nested: list[str]) -> None:
    """Classified data/output boundaries may be omitted; saved source may not."""
    rules = classifications(project)
    tracked = _git(project, ["ls-files", "-z"]).stdout.split("\0")
    for item in nested:
        child = boundary / item
        if child == project or child in project.parents:
            raise SnapshotError(f"Deferred: project lies inside omitted nested Btrfs boundary: {child}")
        if project not in child.parents:
            continue
        relative = child.relative_to(project).as_posix()
        if beneath(relative, rules["durable_data"]):
            continue
        disposable = beneath(relative, rules["disposable_outputs"]) or any(part in _DISPOSABLE for part in Path(relative).parts)
        if disposable and not any(path.startswith(relative + "/") for path in tracked):
            continue
        raise SnapshotError(f"Deferred: saved source nested Btrfs subvolume is nonrecursive and not protected: {child}; classify durable/disposable data precisely or provide separate source capture")
