"""Privileged deletion confined to eligible, managed read-only snapshot leaves."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from ..workspace_paths import get_workspaces_root
from ._models import SnapshotError

# Root runs only the installed, root-owned helper (scripts/summitflow-snapshot-delete), which
# anchors the leaf by directory descriptors and re-checks its identity and UUID before deleting.
SNAPSHOT_DELETE_HELPER = "/usr/local/sbin/summitflow-snapshot-delete"


def managed_store() -> Path:
    """The snapshot store under the real workspace root (the default root is a symlink)."""
    return get_workspaces_root().resolve() / ".snapshots"


def store_path(path: Path) -> Path | None:
    """``path`` rebased onto the real store, or None when it is not beneath the store.

    Manifests record points under any spelling of the workspace root (the
    ``~/.local/share/summitflow/workspaces`` symlink or ``/srv/workspaces``).
    Only the ancestors that spell the root are resolved; components below the
    store are kept literally so a symlink planted there is still refused.
    """
    base = managed_store()
    absolute = path.absolute()
    for ancestor in absolute.parents:
        if ancestor.name == ".snapshots" and ancestor.parent.resolve() == base.parent:
            return base / absolute.relative_to(ancestor)
    return None


def delete_managed_readonly(path: Path, *, recovery_project: str | None = None) -> None:
    """Delete one eligible leaf; callers retain responsibility for policy/locks."""
    target = store_path(path)
    if target is None:
        raise SnapshotError(f"Pruning target is outside the managed snapshot store: {path}")
    parts = target.relative_to(managed_store()).parts
    def safe(value: str) -> bool:
        return bool(re.fullmatch(r"[a-zA-Z0-9._-]+", value)) and value not in {".", ".."}
    if recovery_project is not None:
        valid = len(parts) == 3 and parts[:2] == ("recoveries", recovery_project)
    else:
        valid = len(parts) == 4 and parts[0] != "recoveries" and parts[1] in {"projects", "worktrees"}
    if not valid or not all(safe(part) for part in parts):
        raise SnapshotError(f"Pruning target is not an exact managed snapshot leaf: {path}")
    _privileged_delete(target)


def delete_readonly_residue(path: Path) -> None:
    """Delete one read-only legacy residue subvolume beneath the managed store.

    Residue roots predate the exact point layout, so only containment is
    checked here; the root helper still refuses writable, nested, mounted,
    swapped or foreign-owned targets.
    """
    target = store_path(path)
    if target is None or target == managed_store() or ".." in target.parts:
        raise SnapshotError(f"Residue target is outside the managed snapshot store: {path}")
    _privileged_delete(target)


def _privileged_delete(path: Path) -> None:
    # The root above the store is resolved; the store and everything below it
    # must be real directories before an absent target counts as already clean.
    base = managed_store()
    for ancestor in reversed((path, *path.parents)):
        if (ancestor == base or base in ancestor.parents) and ancestor.is_symlink():
            raise SnapshotError(f"Pruning refuses a symlink component: {ancestor}")
    if not path.exists():
        return
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.getuid():
        raise SnapshotError(f"Pruning target is not owned by the current user: {path}")
    try:
        # The real path keeps the root helper's fixed store and its sudo rule matching.
        subprocess.run(
            ["sudo", "-n", SNAPSHOT_DELETE_HELPER, str(path), str(info.st_dev), str(info.st_ino)],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise SnapshotError(f"Managed read-only snapshot deletion failed: {path}\n{detail}") from exc
