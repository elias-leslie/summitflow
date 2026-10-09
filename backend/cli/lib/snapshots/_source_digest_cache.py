"""Best-effort, per-file digest cache for periodic saved-source checks."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import cast

from ._models import SnapshotError

_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _identity(path: Path) -> tuple[int, int, int, int, int, int] | None:
    try:
        value = path.lstat()
    except FileNotFoundError:
        return None
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _target_identity(path: Path) -> tuple[int, int, int, int, int, int] | None:
    try:
        value = path.stat()
    except FileNotFoundError:
        return None
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _valid_digest(identity: tuple[int, ...], digest: str) -> bool:
    mode = identity[2]
    if stat.S_ISLNK(mode):
        prefix = "symlink:"
    elif stat.S_ISREG(mode):
        prefix = f"{mode & 0o777:o}:"
    else:
        return False
    return digest.startswith(prefix) and bool(_SHA256.fullmatch(digest[len(prefix):]))


def _valid_rules(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    rules = cast(dict[str, object], value)
    for kind in ("durable_data", "disposable_outputs"):
        paths = rules.get(kind)
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            return False
    return True


def _stable_digest(path: Path) -> tuple[tuple[int, ...] | None, str]:
    """Hash only an observation whose path and opened file stayed identical."""
    for _ in range(3):
        before = _identity(path)
        if before is None:
            if _identity(path) is None:
                return None, "missing"
            continue
        mode = before[2]
        if stat.S_ISLNK(mode):
            try:
                value = "symlink:" + hashlib.sha256(os.readlink(path).encode()).hexdigest()
            except FileNotFoundError:
                continue
        elif stat.S_ISREG(mode):
            digest = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    opened = os.fstat(handle.fileno())
                    opened_identity = (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                    if opened_identity != before:
                        continue
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                    closed = os.fstat(handle.fileno())
                    closed_identity = (closed.st_dev, closed.st_ino, closed.st_mode, closed.st_size, closed.st_mtime_ns, closed.st_ctime_ns)
                    if closed_identity != before:
                        continue
            except FileNotFoundError:
                continue
            value = f"{mode & 0o777:o}:" + digest.hexdigest()
        else:
            raise SnapshotError(f"Selected path is not a regular file: {path}")
        if _identity(path) == before:
            return before, value
    raise SnapshotError(f"Selected path changed during source digest: {path}")


class SourceDigestCache:
    """Reuse a digest only for an unchanged full lstat identity."""

    def __init__(self, root: Path, git_dir: Path) -> None:
        self.root = str(root.resolve())
        self.path = git_dir / "st" / "source-digests-v1.json"
        self.previous: dict[str, dict[str, object]] = {}
        self.current: dict[str, dict[str, object]] = {}
        self.previous_storage: dict[str, object] | None = None
        self.current_storage: dict[str, object] | None = None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and type(data.get("version")) is int and data["version"] == _VERSION and data.get("root") == self.root and isinstance(data.get("files"), dict):
                self.previous = data["files"]
                if isinstance(data.get("storage"), dict):
                    self.previous_storage = data["storage"]
        except (OSError, ValueError, UnicodeError):
            pass

    def digest(self, key: str, path: Path) -> str:
        before = _identity(path)
        if before is not None and (stat.S_ISREG(before[2]) or stat.S_ISLNK(before[2])):
            entry = self.previous.get(key)
            if isinstance(entry, dict):
                identity = entry.get("identity")
                value = entry.get("digest")
                if (isinstance(identity, list) and len(identity) == 6
                        and all(type(part) is int for part in identity)
                        and tuple(identity) == before and isinstance(value, str)
                        and _valid_digest(before, value) and _identity(path) == before):
                    self.current[key] = entry
                    return value
        identity, value = _stable_digest(path)
        if identity is not None:
            self.current[key] = {"identity": list(identity), "digest": value}
        return value

    def storage(self, path: Path) -> dict[str, object]:
        """Read classification rules once per metadata identity, without retaining other JSON fields."""
        if not path.is_file():
            return {}
        before = _identity(path)
        if before is not None and stat.S_ISREG(before[2]):
            entry = self.previous_storage
            if isinstance(entry, dict):
                identity = entry.get("identity")
                rules = entry.get("rules")
                if (isinstance(identity, list) and len(identity) == 6
                        and all(type(part) is int for part in identity)
                        and tuple(identity) == before and _valid_rules(rules)
                        and _identity(path) == before):
                    self.current_storage = entry
                    return cast(dict[str, object], rules)
        for _ in range(3):
            before = _identity(path)
            target_before = _target_identity(path)
            if before is None or target_before is None:
                continue
            try:
                with path.open("r") as handle:
                    opened = os.fstat(handle.fileno())
                    opened_identity = (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                    if opened_identity != target_before:
                        continue
                    content = handle.read()
                    closed = os.fstat(handle.fileno())
                    closed_identity = (closed.st_dev, closed.st_ino, closed.st_mode, closed.st_size, closed.st_mtime_ns, closed.st_ctime_ns)
                    if closed_identity != target_before:
                        continue
            except FileNotFoundError:
                continue
            if _identity(path) == before and _target_identity(path) == target_before:
                storage = json.loads(content).get("storage", {})
                if not isinstance(storage, dict):
                    raise SnapshotError("storage must be an object")
                typed_storage = cast(dict[str, object], storage)
                if stat.S_ISREG(before[2]):
                    rules = {kind: typed_storage.get(kind, []) for kind in ("durable_data", "disposable_outputs")}
                    self.current_storage = {"identity": list(before), "rules": rules}
                return typed_storage
        raise SnapshotError(f"Selected path changed during source digest: {path}")

    def save(self) -> None:
        """Cache writes never affect the source result or block a snapshot."""
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({"version": _VERSION, "root": self.root, "files": self.current,
                           "storage": self.current_storage}, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError:
            pass
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    temporary.unlink(missing_ok=True)
