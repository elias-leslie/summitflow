"""Find and remove kept `st check cleanroom --keep-dir` job directories."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import stat
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from . import cleanroom

# ``tempfile.mkdtemp`` suffixes are 8 characters from ``[a-z0-9_]``.
_JOB_NAME = re.compile(r"^(?P<project>[A-Za-z0-9._-]+?)-cleanroom-(?P<suffix>[a-z0-9_]{8})$")
_DURATION = re.compile(r"^(?P<value>\d+(?:\.\d+)?)(?P<unit>[smhdw]?)$")
_UNIT_SECONDS = {"": 3600, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


@dataclass(frozen=True)
class CleanroomJob:
    path: Path
    project: str
    age_seconds: float
    size_bytes: int
    skip_reason: str | None = None


def parse_age(raw: str) -> float:
    """Parse ``90s``/``30m``/``24h``/``2d``/``1w`` (bare number = hours) into seconds."""
    match = _DURATION.match(raw.strip().lower())
    if not match:
        raise ValueError(f"invalid duration {raw!r}; use e.g. 30m, 24h, 2d")
    return float(match["value"]) * _UNIT_SECONDS[match["unit"]]


def cleanroom_parent() -> Path:
    """The validated parent new cleanrooms are created in."""
    parent = cleanroom._cleanroom_temp_parent()
    return parent if parent is not None else Path(tempfile.gettempdir())


def live_cwds(proc_root: Path = Path("/proc")) -> set[Path]:
    """Current working directories of visible processes (unreadable ones are ignored)."""
    cwds: set[Path] = set()
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return cwds
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            cwds.add(Path(os.readlink(entry / "cwd")))
        except OSError:
            continue
    return cwds


def tree_disk_bytes(root: Path) -> int:
    """Allocated bytes under root without following symlinks; hardlinks counted once."""
    seen: set[tuple[int, int]] = set()
    total = 0
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        for name in (*dirnames, *filenames):
            try:
                info = os.lstat(os.path.join(directory, name))
            except OSError:
                continue
            key = (info.st_dev, info.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += info.st_blocks * 512
    with contextlib.suppress(OSError):
        total += os.lstat(root).st_blocks * 512
    return total


def _last_activity(path: Path) -> float:
    """Newest mtime of the job dir and its direct children (repo/home/tmp)."""
    newest = path.lstat().st_mtime
    try:
        for child in path.iterdir():
            try:
                newest = max(newest, child.lstat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return newest


def _in_use(path: Path, cwds: Iterable[Path]) -> bool:
    return any(cwd == path or cwd.is_relative_to(path) for cwd in cwds)


def find_cleanroom_jobs(
    parent: Path,
    *,
    older_than: float,
    project: str | None = None,
    now: float | None = None,
    cwds: Iterable[Path] | None = None,
    measure: bool = True,
) -> list[CleanroomJob]:
    """Job dirs in parent older than ``older_than`` seconds; skipped ones carry a reason."""
    now = time.time() if now is None else now
    active = set(live_cwds() if cwds is None else cwds)
    jobs: list[CleanroomJob] = []
    for entry in sorted(parent.iterdir()):
        match = _JOB_NAME.match(entry.name)
        if not match or (project is not None and match["project"] != project):
            continue
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode):
            jobs.append(CleanroomJob(entry, match["project"], 0.0, 0, "symlink refused"))
            continue
        if not stat.S_ISDIR(info.st_mode):
            continue
        if info.st_uid != os.getuid():
            jobs.append(CleanroomJob(entry, match["project"], 0.0, 0, "owned by another user"))
            continue
        age = now - _last_activity(entry)
        if age < older_than:
            continue
        resolved = entry.resolve()
        reason = "in use by a live process" if _in_use(resolved, active) else None
        size = tree_disk_bytes(entry) if measure else 0
        jobs.append(CleanroomJob(entry, match["project"], age, size, reason))
    return jobs


def remove_job(job: CleanroomJob) -> None:
    """Remove one job directory; refuses symlinks (shutil.rmtree never follows them)."""
    if job.skip_reason is not None:
        raise ValueError(f"refusing to remove {job.path}: {job.skip_reason}")
    if job.path.is_symlink() or not job.path.is_dir():
        raise ValueError(f"refusing to remove non-directory or symlink {job.path}")
    shutil.rmtree(job.path)


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"
