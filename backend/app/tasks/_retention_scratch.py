"""Report-only age review of disposable ``/srv/scratch`` entries.

Scratch is excluded from backups, so nothing here deletes. Each direct child of
an allowlisted root is reviewed as one unit and is reported only when it is old,
not a symlink target, not open by a visible process and not a protected root.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

SCRATCH_ROOT = Path("/srv/scratch")
# Long-lived caches/models and namespaces whose owners already run retention
# (cleanrooms, restores, backups, acceptance) are never review candidates.
PROTECTED_NAMES = frozenset({"cache", "models", ".dev-tools"})
PROTECTED_PREFIXES = ("st-",)
DEFAULT_SYMLINK_DEPTH = 4
DEFAULT_MAX_ENTRIES = 200_000


class ScratchCandidate(TypedDict):
    path: str
    age_hours: float
    size_bytes: int
    entries: int
    action: str


class ScratchSkip(TypedDict):
    path: str
    reason: str


class ScratchReview(TypedDict):
    status: str
    root: str
    max_age_hours: int
    candidates: list[ScratchCandidate]
    protected: list[ScratchSkip]
    recent: int
    process_visibility: str


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _link_target(link: Path) -> list[Path]:
    """Literal and fully resolved targets; either may name scratch."""
    try:
        literal = Path(os.path.normpath(link.parent / os.readlink(link)))
    except OSError:
        return []
    targets = [literal]
    try:
        resolved = link.resolve(strict=False)
    except (OSError, RuntimeError):
        return targets
    return targets if resolved == literal else [*targets, resolved]


def symlink_references(
    roots: Iterable[Path], *, scratch_root: Path, max_depth: int = DEFAULT_SYMLINK_DEPTH,
) -> list[tuple[Path, Path]]:
    """Return ``(link, target)`` for symlinks under *roots* that point into scratch.

    The walk is depth-bounded, never follows links, stays on each root's
    filesystem and skips ``.snapshots``, matching ``find -maxdepth N -xdev``.
    """
    references: list[tuple[Path, Path]] = []
    for root in roots:
        try:
            device = root.lstat().st_dev
        except OSError:
            continue
        base_depth = len(root.parts)
        for current, dirs, files in os.walk(root, followlinks=False, onerror=lambda _: None):
            current_path = Path(current)
            depth = len(current_path.parts) - base_depth
            kept = []
            for name in dirs:
                child = current_path / name
                if child.is_symlink():
                    files.append(name)
                    continue
                if name == ".snapshots" or depth + 1 >= max_depth:
                    continue
                try:
                    if child.lstat().st_dev != device:
                        continue
                except OSError:
                    continue
                kept.append(name)
            dirs[:] = kept
            for name in files:
                link = current_path / name
                if not link.is_symlink():
                    continue
                for target in _link_target(link):
                    if _within(target, scratch_root):
                        references.append((link, target))
    return references


def open_scratch_paths(scratch_root: Path, proc_root: Path = Path("/proc")) -> tuple[dict[Path, int], bool]:
    """Map scratch paths held by visible processes (cwd, root, exe, fds, maps) to a pid.

    Returns ``(paths, complete)``; ``complete`` is false when any process could
    not be inspected, so callers can report reduced visibility.
    """
    held: dict[Path, int] = {}
    complete = True
    try:
        entries = [entry for entry in proc_root.iterdir() if entry.name.isdigit()]
    except OSError:
        return held, False
    for entry in entries:
        pid = int(entry.name)
        links = [entry / "cwd", entry / "root", entry / "exe"]
        try:
            links.extend(entry / "fd" / fd for fd in os.listdir(entry / "fd"))
        except PermissionError:
            complete = False
        except OSError:
            continue
        for link in links:
            try:
                target = Path(os.readlink(link))
            except PermissionError:
                complete = False
                continue
            except OSError:
                continue
            if _within(target, scratch_root):
                held.setdefault(target, pid)
        try:
            maps = (entry / "maps").read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            complete = False
            continue
        except OSError:
            continue
        for line in maps.splitlines():
            fields = line.split(maxsplit=5)
            if len(fields) == 6 and fields[5].startswith("/"):
                target = Path(fields[5].removesuffix(" (deleted)"))
                if _within(target, scratch_root):
                    held.setdefault(target, pid)
    return held, complete


def _activity(info: os.stat_result) -> float:
    # Directory atime would be refreshed by this scan itself on relatime mounts.
    if stat.S_ISDIR(info.st_mode):
        return max(info.st_mtime, info.st_ctime)
    return max(info.st_mtime, info.st_ctime, info.st_atime)


def _tree_stats(path: Path, *, max_entries: int) -> tuple[float, int, int] | None:
    """Newest activity (file mtime/ctime/atime, dir mtime/ctime), size and entry count; None past the cap."""
    info = path.lstat()
    newest = _activity(info)
    size = info.st_size
    count = 1
    if not path.is_dir() or path.is_symlink():
        return newest, size, count
    for current, dirs, files in os.walk(path, followlinks=False):
        for name in (*dirs, *files):
            count += 1
            if count > max_entries:
                return None
            try:
                child = os.lstat(os.path.join(current, name))
            except OSError:
                continue
            newest = max(newest, _activity(child))
            size += child.st_size
    return newest, size, count


def collect_scratch_review(
    *,
    max_age_hours: int,
    now: datetime | None = None,
    scratch_root: Path = SCRATCH_ROOT,
    symlink_roots: Sequence[Path] | None = None,
    proc_root: Path = Path("/proc"),
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> ScratchReview:
    """Report old, unreferenced, unused scratch entries; never deletes."""
    effective_now = now or datetime.now(UTC)
    review = ScratchReview(
        status="report_only", root=str(scratch_root), max_age_hours=max_age_hours,
        candidates=[], protected=[], recent=0, process_visibility="complete",
    )
    if not scratch_root.is_dir() or scratch_root.is_symlink():
        review["status"] = "skipped"
        return review
    roots = list(symlink_roots) if symlink_roots is not None else [Path.home(), Path("/srv/workspaces/projects")]
    references = symlink_references([*roots, scratch_root], scratch_root=scratch_root)
    held, complete = open_scratch_paths(scratch_root, proc_root)
    if not complete:
        review["process_visibility"] = "partial"
    cutoff = effective_now.timestamp() - max_age_hours * 3600
    for child in sorted(scratch_root.iterdir()):
        name = child.name
        if child.is_symlink():
            continue
        if name in PROTECTED_NAMES or name.startswith(PROTECTED_PREFIXES):
            review["protected"].append(ScratchSkip(path=str(child), reason="protected root"))
            continue
        link = next((link for link, target in references
                     if _within(target, child) and not _within(link, child)), None)
        if link is not None:
            review["protected"].append(ScratchSkip(path=str(child), reason=f"symlink target of {link}"))
            continue
        pid = next((pid for target, pid in held.items() if _within(target, child)), None)
        if pid is not None:
            review["protected"].append(ScratchSkip(path=str(child), reason=f"in use by pid {pid}"))
            continue
        try:
            stats = _tree_stats(child, max_entries=max_entries)
        except OSError as exc:
            review["protected"].append(ScratchSkip(path=str(child), reason=f"unreadable: {exc.strerror or exc}"))
            continue
        if stats is None:
            review["protected"].append(ScratchSkip(path=str(child), reason=f"over {max_entries} entries; not verified"))
            continue
        newest, size, entries = stats
        if newest > cutoff:
            review["recent"] += 1
            continue
        review["candidates"].append(ScratchCandidate(
            path=str(child), age_hours=round((effective_now.timestamp() - newest) / 3600, 1),
            size_bytes=size, entries=entries, action="review_only",
        ))
    return review
