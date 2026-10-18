"""Agent and build temp in /tmp: whole units that nothing changed for a while and no process holds.

A unit is an agent session dir (``/tmp/claude-*/<project>/<session>``) or a top-level build temp entry
(``go-build*``, ``node-compile-cache`` ...). Only the owner's own entries are considered. Before removal each unit is
checked again: unchanged since the scan, not open by any visible process, no mount inside or of it; removal goes
through directory fds and never crosses a device or mount (``remove_entry``).
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ._retention_scratch import (
    MOUNTINFO,
    _tree_stats,
    mount_skip_reason,
    open_scratch_paths,
    remove_entry,
)

TMP_ROOT = Path("/tmp")
AGENT_PREFIXES = ("claude-",)
BUILD_PATTERNS = ("go-build*", "node-compile-cache", "neri-*", "st-*-go-cache",
                  "com.google.Chrome.chrome_chrome_url_fetcher_*")
MAX_ENTRIES = 500_000


def _dirs(path: Path) -> list[Path]:
    try:
        return [c for c in sorted(path.iterdir()) if not c.is_symlink() and c.is_dir()]
    except OSError:
        return []


def agent_tmp_units(root: Path = TMP_ROOT, uid: int | None = None) -> list[tuple[Path, str]]:
    """(unit, kind) pairs the owner may remove; kind is "agent" or "build"."""
    uid = os.getuid() if uid is None else uid
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return []
    units: list[tuple[Path, str]] = []
    for entry in entries:
        try:
            info = entry.lstat()
        except OSError:
            continue
        if entry.is_symlink() or info.st_uid != uid:
            continue
        if entry.name.startswith(AGENT_PREFIXES) and entry.is_dir():
            units += [(session, "agent") for project in _dirs(entry) for session in _dirs(project)]
        elif any(fnmatch.fnmatchcase(entry.name, pattern) for pattern in BUILD_PATTERNS):
            units.append((entry, "build"))
    return units


def age_agent_tmp(
    *,
    agent_max_age_hours: int,
    build_max_age_hours: int,
    now: datetime,
    root: Path = TMP_ROOT,
    pressured: Callable[[], bool] | None = None,
    dry_run: bool = False,
    proc_root: Path = Path("/proc"),
    mountinfo: Path = MOUNTINFO,
) -> dict[str, Any]:
    """Remove stale units, oldest first; with ``pressured``, stop as soon as it reports False."""
    result: dict[str, Any] = {"step": "agent_tmp", "status": "success", "deleted_paths": [], "bytes": 0, "kept": []}
    stale: list[tuple[float, Path, tuple[int, int], int]] = []
    for unit, kind in agent_tmp_units(root):
        cutoff = now.timestamp() - (agent_max_age_hours if kind == "agent" else build_max_age_hours) * 3600
        try:
            info = unit.lstat()
            stats = _tree_stats(unit, max_entries=MAX_ENTRIES)
        except OSError as exc:
            result["kept"].append({"path": str(unit), "reason": exc.strerror or str(exc)})
            continue
        if stats is not None and stats[0] <= cutoff:
            stale.append((stats[0], unit, (info.st_dev, info.st_ino), stats[1]))
    for newest, unit, ident, size in sorted(stale, key=lambda row: row[0]):
        if pressured is not None and not pressured():
            break
        try:
            again = _tree_stats(unit, max_entries=MAX_ENTRIES)
        except OSError as exc:
            result["kept"].append({"path": str(unit), "reason": exc.strerror or str(exc)})
            continue
        if again is None or again[0] > newest:
            result["kept"].append({"path": str(unit), "reason": "changed since the scan"})
            continue
        mounted = mount_skip_reason(unit, mountinfo)
        if mounted is not None:
            result["kept"].append({"path": str(unit), "reason": mounted})
            continue
        held, _ = open_scratch_paths(unit, proc_root)
        if held:
            result["kept"].append({"path": str(unit), "reason": "in use"})
            continue
        if not dry_run:
            try:
                remove_entry(unit, ident)
            except OSError as exc:
                result.update(status="partial", error=str(exc))
                continue
        result["deleted_paths"].append(str(unit))
        result["bytes"] += size
    result["kept"] = result["kept"][:20]
    return result
