"""Cancellable, metadata-only disk attribution within mounted filesystems.

The walk is intrinsically unbounded on a general filesystem, so entry count,
depth and wall time are independent hard caps. Reported bytes are observed
file sizes, not allocated blocks or a complete filesystem usage figure.
"""
from __future__ import annotations

import os
import re
import stat
import time
from collections.abc import Callable
from pathlib import Path

from monitor_observe.common import ObserveQueryError, availability, base, error, item, limits, pack

MAX_ENTRIES = 10_000
MAX_DEPTH = 12
MAX_SECONDS = 5.0


def _mount_roots() -> tuple[Path, ...]:
    """Read kernel mountpoints, longest first, without trusting request paths."""
    roots = {Path("/")}
    try:
        with Path("/proc/self/mountinfo").open(encoding="utf-8") as stream:
            for line in stream:
                fields = line.split(" - ", 1)[0].split()
                if len(fields) < 5:
                    continue
                mountpoint = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4])
                path = Path(mountpoint)
                if path.is_absolute():
                    roots.add(path)
    except OSError:
        pass
    return tuple(sorted(roots, key=lambda path: (-len(path.parts), str(path))))


def _scope(path: str | Path) -> tuple[str, Path, tuple[str, ...]]:
    if not isinstance(path, (str, Path)) or not str(path) or not Path(path).is_absolute():
        raise ObserveQueryError("path must be an absolute path on a mounted filesystem")
    candidate = Path(path)
    if ".." in candidate.parts:
        raise ObserveQueryError("parent traversal is not allowed")
    current = Path("/")
    for part in candidate.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ObserveQueryError("symlink path is not allowed")
    for root in _mount_roots():
        try:
            parts = candidate.relative_to(root.absolute()).parts
        except ValueError:
            continue
        return "mount", root, parts
    raise ObserveQueryError("path is not on a mounted filesystem")


def query_disk_space(path: str | Path, *, max_entries: int = 1024,
                     max_depth: int = 6, limit: int = 10, max_bytes: int = 4096,
                     timeout_seconds: float = 2.0,
                     cancelled: Callable[[], bool] | None = None) -> dict:
    """Attribute visible regular-file sizes without following links or reading contents.

    `cancelled` is an optional callback checked between entries. A partial result
    has `truncated=true`, its stop reason, and scanned/omitted coverage.
    """
    limits(limit, max_bytes)
    if type(max_entries) is not int or not 1 <= max_entries <= MAX_ENTRIES:
        raise ObserveQueryError(f"max_entries must be 1..{MAX_ENTRIES}")
    if type(max_depth) is not int or not 0 <= max_depth <= MAX_DEPTH:
        raise ObserveQueryError(f"max_depth must be 0..{MAX_DEPTH}")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= MAX_SECONDS:
        raise ObserveQueryError(f"timeout_seconds must be >0..{MAX_SECONDS}")
    if cancelled is not None and not callable(cancelled):
        raise ObserveQueryError("cancelled must be callable")
    label, root, parts = _scope(path)
    payload = base("disk_space", {"scope": label, "depth": len(parts),
                                  "max_entries": max_entries, "max_depth": max_depth})
    deadline = time.monotonic() + timeout_seconds
    scanned = skipped = denied = 0
    stop: str | None = None
    entries: list[tuple[str, int, str]] = []
    root_fd: int | None = None
    target_fd: int | None = None
    root_dev: int | None = None

    def expired() -> bool:
        nonlocal stop
        if stop:
            return True
        if cancelled and cancelled():
            stop = "cancelled"
        elif time.monotonic() >= deadline:
            stop = "timeout"
        elif scanned >= max_entries:
            stop = "entry_cap"
        return stop is not None

    def walk(fd: int, depth: int) -> int:
        nonlocal scanned, skipped, denied, stop
        total = 0
        if depth > max_depth:
            stop = stop or "depth_cap"
            return 0
        try:
            with os.scandir(fd) as stream:
                for entry in stream:
                    if expired():
                        break
                    scanned += 1
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except PermissionError:
                        denied += 1
                        continue
                    except OSError:
                        skipped += 1
                        continue
                    if info.st_dev != root_dev or stat.S_ISLNK(info.st_mode):
                        skipped += 1
                        continue
                    size = 0
                    kind = "file"
                    if stat.S_ISREG(info.st_mode):
                        size = info.st_size
                    elif stat.S_ISDIR(info.st_mode):
                        kind = "directory"
                        if depth == max_depth:
                            stop = stop or "depth_cap"
                        else:
                            try:
                                child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                                dir_fd=fd)
                                try:
                                    if os.fstat(child).st_dev != root_dev:
                                        skipped += 1
                                    else:
                                        size = walk(child, depth + 1)
                                finally:
                                    os.close(child)
                            except PermissionError:
                                denied += 1
                            except OSError:
                                skipped += 1
                    else:
                        skipped += 1
                        continue
                    total += size
                    if depth == 0:
                        entries.append((entry.name, size, kind))
        except PermissionError:
            denied += 1
        return total

    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        root_dev = os.fstat(root_fd).st_dev
        target_fd = os.dup(root_fd)
        for part in parts:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=target_fd)
            os.close(target_fd)
            target_fd = next_fd
            if os.fstat(target_fd).st_dev != root_dev:
                raise ObserveQueryError("cross-filesystem path is not allowed")
        walk(target_fd, 0)
    except OSError as exc:
        code = availability(exc)
        payload["errors"].append(error(code, "filesystem"))
        stop = stop or code
    finally:
        if target_fd is not None:
            os.close(target_fd)
        if root_fd is not None:
            os.close(root_fd)
    entries.sort(key=lambda row: (-row[1], row[0]))
    complete = stop is None and denied == 0 and skipped == 0
    payload["coverage"] = {"availability": "ok" if complete else "partial",
                           "scope": label, "mountpoint": str(root), "entries_scanned": scanned, "entries_hidden_or_skipped": skipped,
                           "entries_permission_denied": denied,
                           "stop_reason": stop or ("permission_denied" if denied else "excluded_entries" if skipped else None),
                           "bytes_observed": sum(size for _, size, _ in entries),
                           "complete": complete,
                           "measure": "regular_file_apparent_bytes"}
    if stop:
        payload["errors"].append(error("source_truncated" if stop in {"entry_cap", "depth_cap"} else stop,
                                       "filesystem"))
    rows = [item("filesystem", "os.scandir", "ok", {"name": name, "kind": kind,
                                                    "apparent_bytes": size}, unit="bytes")
            for name, size, kind in entries]
    return pack(payload, rows, limit=limit, max_bytes=max_bytes,
                more=bool(stop or denied or skipped or len(rows) > limit))
