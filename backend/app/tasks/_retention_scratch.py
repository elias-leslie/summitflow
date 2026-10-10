"""Age review and weekly cleanup of disposable ``/srv/scratch`` entries.

Each direct child of the scratch root is reviewed as one unit and is a
candidate only when it is old, not a symlink target, not open by a visible
process and not a protected root. ``collect_scratch_review`` never deletes;
``apply_scratch_retention`` re-verifies each candidate and removes it, and the
host-retention maintenance step runs it at most weekly. Scratch is excluded
from backups and holds only replaceable data.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

SCRATCH_ROOT = Path("/srv/scratch")
# Long-lived caches/models and namespaces whose owners already run retention
# (cleanrooms, restores, backups, acceptance) are never review candidates.
PROTECTED_NAMES = frozenset({"cache", "models", ".dev-tools"})
PROTECTED_PREFIXES = ("st-",)
DEFAULT_SYMLINK_DEPTH = 4
DEFAULT_MAX_ENTRIES = 200_000
APPLY_INTERVAL_HOURS = 7 * 24
DEFAULT_STAMP = Path.home() / ".local/state/summitflow/scratch-retention.json"


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


class ScratchApply(TypedDict):
    status: str
    root: str
    max_age_hours: int
    deleted_paths: list[str]
    bytes_reclaimed: int
    kept: list[ScratchSkip]
    protected: int
    process_visibility: str


def apply_scratch_retention(
    *,
    max_age_hours: int,
    now: datetime | None = None,
    scratch_root: Path = SCRATCH_ROOT,
    symlink_roots: Sequence[Path] | None = None,
    proc_root: Path = Path("/proc"),
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> ScratchApply:
    """Delete review candidates after re-checking each one immediately before removal.

    Only direct, non-symlink children owned by this user on the scratch device
    are removed. Age includes file atime, so anything read within the window
    keeps its entry even when its process is not visible.
    """
    effective_now = now or datetime.now(UTC)
    review = collect_scratch_review(
        max_age_hours=max_age_hours, now=effective_now, scratch_root=scratch_root,
        symlink_roots=symlink_roots, proc_root=proc_root, max_entries=max_entries,
    )
    result = ScratchApply(
        status="skipped" if review["status"] == "skipped" else "success", root=str(scratch_root),
        max_age_hours=max_age_hours, deleted_paths=[], bytes_reclaimed=0, kept=[],
        protected=len(review["protected"]), process_visibility=review["process_visibility"],
    )
    if not review["candidates"]:
        return result
    device = scratch_root.lstat().st_dev
    cutoff = effective_now.timestamp() - max_age_hours * 3600
    held, _ = open_scratch_paths(scratch_root, proc_root)
    for candidate in review["candidates"]:
        path = Path(candidate["path"])
        try:
            info = path.lstat()
            if path.parent != scratch_root or stat.S_ISLNK(info.st_mode) or info.st_dev != device or info.st_uid != os.getuid():
                result["kept"].append(ScratchSkip(path=str(path), reason="not a user-owned scratch entry"))
                continue
            if any(_within(target, path) for target in held):
                result["kept"].append(ScratchSkip(path=str(path), reason="in use"))
                continue
            stats = _tree_stats(path, max_entries=max_entries)
            if stats is None or stats[0] > cutoff:
                result["kept"].append(ScratchSkip(path=str(path), reason="changed since review"))
                continue
            if stat.S_ISDIR(info.st_mode):
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as exc:
            result["kept"].append(ScratchSkip(path=str(path), reason=f"delete failed: {exc.strerror or exc}"))
            result["status"] = "partial"
            continue
        result["deleted_paths"].append(str(path))
        result["bytes_reclaimed"] += stats[1]
    return result


def _read_stamp(stamp: Path) -> datetime | None:
    try:
        value = datetime.fromisoformat(json.loads(stamp.read_text())["last_applied_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _write_stamp(stamp: Path, at: datetime, result: ScratchApply) -> None:
    stamp.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".scratch-retention-", dir=stamp.parent)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"last_applied_at": at.isoformat(), "status": result["status"],
                   "deleted": len(result["deleted_paths"]), "bytes_reclaimed": result["bytes_reclaimed"]}, stream)
    os.replace(temporary, stamp)


def weekly_scratch_retention(
    *, max_age_hours: int, now: datetime | None = None, stamp: Path = DEFAULT_STAMP, **kwargs: Any,
) -> dict[str, Any]:
    """Run ``apply_scratch_retention`` when the last apply is a week old (daily caller)."""
    effective_now = now or datetime.now(UTC)
    last = _read_stamp(stamp)
    # A few hours of slack keeps a daily caller from drifting to an eight-day cadence.
    if last is not None and effective_now - last < timedelta(hours=APPLY_INTERVAL_HOURS - 6):
        return {"status": "skipped", "reason": "weekly-cadence", "last_applied_at": last.isoformat()}
    result = apply_scratch_retention(max_age_hours=max_age_hours, now=effective_now, **kwargs)
    if result["status"] != "skipped":
        _write_stamp(stamp, effective_now, result)
    return {**result}
