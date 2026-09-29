#!/usr/bin/env python3
"""Read-only metadata inventory for explicitly named agent/AFT source roots."""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ALLOWED_ROOT_NAMES = {".codex", ".claude", "aftertimes", "theaftertimes", "aft"}
SENSITIVE_NAMES = {
    "auth.json", "credentials.json", ".credentials.json", "credentials", "rclone.conf", ".env", ".env.local",
    "backup-keys", ".ssh", ".gnupg", ".aws", "secrets", ".secrets",
    "token.json", "tokens.json", "password", "password.txt",
}
PROTECTED_NAMES = {
    ".git", ".jj", "sessions", "transcripts", "conversations", "history",
    "state", "memories", "memory", "projects", "skills", "plans",
    "assets", "art", "originals", "source-art", "licenses", "licensing",
    "receipts", "current", "previous",
}
ART_SUFFIXES = {".blend", ".psd", ".ase", ".aseprite", ".kra", ".svg", ".png", ".jpg", ".jpeg", ".wav", ".ogg"}
GENERATED_NAMES = {
    "cache", "caches", ".cache", "downloads", "download-cache",
    "dist", "build", "exports", "renders", "temp", "tmp", ".tmp",
    "node_modules", ".venv", ".next", "__pycache__", ".pytest_cache", ".ruff_cache",
}


def classify(relative: Path, protected: bool) -> str:
    parts = {part.lower() for part in relative.parts}
    name = relative.name.lower()
    if protected or parts & PROTECTED_NAMES or name.endswith(".jsonl") or name.startswith(("license", "copyright")):
        return "protected-recovery"
    if relative.suffix.lower() in ART_SUFFIXES:
        return "protected-art-or-original"
    if parts & {"releases", "installed-releases", "release-packages"}:
        return "review-release-status"
    if parts & GENERATED_NAMES or any(part.startswith(".tmp-") for part in parts):
        return "review-generated"
    if parts & {"logs", "log"} or name.endswith(".log"):
        return "review-diagnostic-log"
    return "protected-unclassified"


def inventory(
    roots: list[Path], *, protected_paths: list[Path], older_than_days: float,
    max_entries: int, now: float | None = None,
) -> dict[str, Any]:
    """Use lstat/scandir only. Never open files, resolve links, or delete data."""
    timestamp = time.time() if now is None else now
    entries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    totals: dict[str, int] = defaultdict(int)
    seen: set[tuple[int, int]] = set()
    truncated = False

    def walk(path: Path, root: Path, parent_fd: int | None = None) -> None:
        nonlocal truncated
        if len(entries) >= max_entries:
            truncated = True
            return
        relative = path.relative_to(root)
        if path.name.lower() in SENSITIVE_NAMES:
            entries.append({"root": str(root), "path": relative.as_posix(), "category": "sensitive-skipped"})
            return
        try:
            metadata = path.lstat() if parent_fd is None else os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            errors.append({"root": str(root), "path": relative.as_posix(), "error": "metadata-unreadable"})
            return
        mode = metadata.st_mode
        category = classify(relative, any(path == protected or path.is_relative_to(protected) for protected in protected_paths))
        kind = "directory" if stat.S_ISDIR(mode) else "file" if stat.S_ISREG(mode) else "symlink" if stat.S_ISLNK(mode) else "special"
        if kind in {"symlink", "special"}:
            category = "link-skipped" if kind == "symlink" else "special-skipped"
        identity = (metadata.st_dev, metadata.st_ino)
        allocated = int(getattr(metadata, "st_blocks", 0)) * 512
        accounted = 0 if identity in seen else allocated
        seen.add(identity)
        age_days = max(0.0, (timestamp - metadata.st_mtime) / 86400)
        totals[category] += accounted
        entries.append({
            "root": str(root), "path": relative.as_posix(), "kind": kind,
            "category": category, "size_bytes": metadata.st_size,
            "allocated_bytes": accounted, "hardlink_already_counted": accounted == 0 and allocated > 0,
            "age_days": round(age_days, 2), "older_than_threshold": age_days >= older_than_days,
        })
        if kind != "directory":
            return
        descriptor = -1
        try:
            descriptor = os.open(path if parent_fd is None else path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            pinned = os.fstat(descriptor)
            if (pinned.st_dev, pinned.st_ino) != identity:
                raise OSError("directory changed")
            limited = False
            names = []
            with os.scandir(descriptor) as children:
                remaining = max_entries - len(entries)
                for child in children:
                    if len(names) >= remaining:
                        limited = True
                        break
                    names.append(child.name)
            names.sort()
            for name in names:
                walk(path / name, root, descriptor)
                if truncated:
                    break
            truncated = truncated or limited
        except OSError:
            errors.append({"root": str(root), "path": relative.as_posix(), "error": "directory-unreadable"})
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    for root in roots:
        walk(root, root)
        if truncated:
            break
    return {
        "schema_version": 1, "read_only": True,
        "observed_at": datetime.fromtimestamp(timestamp, UTC).isoformat(),
        "complete": not truncated and not errors, "truncated": truncated,
        "older_than_days": older_than_days,
        "allocated_bytes": sum(totals.values()), "allocated_bytes_by_category": dict(totals),
        "entries": entries, "errors": errors,
        "limitations": [
            "Age and path names do not establish inactivity or permission to remove a file.",
            "Protected originals, transcripts, Git and state take precedence over generated-directory names.",
            "Release status requires a separate operator review; pass known active paths with --protected-path.",
            "Credential-named paths and symlink targets are not inspected; allocated blocks are filesystem estimates.",
            "No Veeam role or policy is inferred; its seven-point image policy remains unchanged.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", required=True, type=Path, help="Explicit absolute .codex, .claude, AfterTimes/AFT root; repeatable")
    parser.add_argument("--protected-path", action="append", default=[], type=Path, help="Explicit active/original path to protect; repeatable")
    parser.add_argument("--older-than-days", default=30.0, type=float)
    parser.add_argument("--max-entries", default=25000, type=int)
    args = parser.parse_args(argv)
    if not math.isfinite(args.older_than_days) or args.older_than_days < 0 or not 1 <= args.max_entries <= 100000:
        parser.error("Age must be nonnegative and max entries must be between 1 and 100000")
    roots = []
    try:
        for root in args.root:
            normalized_name = root.name.lower().replace("-", "").replace("_", "")
            if not root.is_absolute() or ".." in root.parts or normalized_name not in ALLOWED_ROOT_NAMES:
                parser.error("Each root must be an absolute, narrow .codex/.claude/AfterTimes/AFT path")
            if not stat.S_ISDIR(root.lstat().st_mode):
                parser.error("Roots must be real directories; root symlinks are refused")
            # Check ancestors with lstat rather than resolving or walking links.
            if any(stat.S_ISLNK(parent.lstat().st_mode) for parent in root.parents):
                parser.error("Root ancestors must not be symlinks")
            if root not in roots:
                roots.append(root)
        for protected in args.protected_path:
            if not protected.is_absolute() or ".." in protected.parts or not any(protected.is_relative_to(root) for root in roots):
                parser.error("Protected paths must be absolute and within an assigned root")
    except OSError:
        parser.error("An explicit root or ancestor is unavailable")
    report = inventory(roots, protected_paths=args.protected_path, older_than_days=args.older_than_days, max_entries=args.max_entries)
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
