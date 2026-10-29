"""Reusable passing result of `st check --quick --changed-only`.

`st commit` runs the quick check on the files it is about to commit. When the
same files already passed that check and nothing the check reads has changed,
the second run proves nothing new. A receipt records the content hash of every
file the passing run covered plus a context hash (HEAD, gate configuration and
environment, the st code that ran the check). It is reused only when every file
in the new scope has the same hash and the context is identical; any difference
means the check runs. A receipt is written only after a passing run whose scope
files did not change while it ran.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from cli.lib.acceptance import _INPUT_NAMES, _hash_parts, _receipt_local_inputs

_VERSION = 1
_KEEP = 16
_DEFAULT_TTL_SECONDS = 3600.0
_ABSENT = "absent"


def enabled() -> bool:
    """ST_QUICK_RECEIPTS=0 turns reuse and recording off (the test suite does, to stay off real checkouts)."""
    return os.environ.get("ST_QUICK_RECEIPTS") != "0"


def _git(repo: Path, args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "--no-optional-locks", *args], cwd=repo, capture_output=True, check=False
        )
    except OSError as exc:  # missing checkout or git: nothing to reuse
        return subprocess.CompletedProcess(list(args), 127, b"", str(exc).encode())


def ttl_seconds() -> float:
    try:
        return float(os.environ.get("ST_QUICK_REUSE_SECONDS", _DEFAULT_TTL_SECONDS))
    except ValueError:
        return _DEFAULT_TTL_SECONDS


def _store_path(repo: Path) -> Path | None:
    result = _git(repo, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    if result.returncode or not result.stdout.strip():
        return None
    return Path(result.stdout.decode().strip()) / "st" / "quick-check.json"


def file_hash(repo: Path, relative: str) -> str:
    path = repo / relative
    try:
        if path.is_symlink():
            return "link:" + os.readlink(path)
        if path.is_file():
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        return "unreadable"
    return _ABSENT if not path.exists() else "other"


def scope_hashes(repo: Path, files: Sequence[str]) -> dict[str, str]:
    return {name: file_hash(repo, name) for name in sorted(set(files))}


def _config_file_hashes(repo: Path) -> list[bytes]:
    listed = _git(repo, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    if listed.returncode:
        raise OSError("cannot list gate configuration files")
    parts: list[bytes] = []
    for name in sorted(item for item in listed.stdout.decode(errors="replace").split("\0") if item):
        if Path(name).name in _INPUT_NAMES:
            parts.append(f"{name}\0{file_hash(repo, name)}".encode())
    return parts


def _tool_identity() -> bytes:
    """The st code that runs the check, by size and mtime: any deploy or edit changes it."""
    backend = Path(__file__).resolve().parents[2]
    paths = sorted((backend / "cli").rglob("*.py"))
    paths.append(backend.parent / "scripts" / "lib" / "tool-registry.json")
    parts: list[bytes] = []
    for path in paths:
        try:
            info = path.stat()
        except OSError:
            continue
        parts.append(f"{path.relative_to(backend.parent)}\0{info.st_size}\0{info.st_mtime_ns}".encode())
    return _hash_parts(parts).encode()


def context_hash(repo: Path) -> str | None:
    """Everything besides the scope files that a passing quick check depends on."""
    head = _git(repo, ["rev-parse", "--verify", "HEAD"])
    if head.returncode:
        return None
    try:
        inputs = json.dumps(_receipt_local_inputs(repo), sort_keys=True, default=str).encode()
        return _hash_parts([head.stdout.strip(), inputs, *_config_file_hashes(repo), _tool_identity()])
    except (OSError, RuntimeError, ValueError):  # AcceptanceError is a RuntimeError
        return None


def _load(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("receipts") if isinstance(data, dict) and data.get("version") == _VERSION else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def reusable(repo: Path, files: Sequence[str], *, now: float | None = None) -> dict[str, Any] | None:
    """The newest receipt whose files include every scope file with identical content."""
    if not files or not enabled():
        return None
    path = _store_path(repo)
    if path is None:
        return None
    receipts = _load(path)
    if not receipts:
        return None
    context = context_hash(repo)
    if context is None:
        return None
    current = scope_hashes(repo, files)
    moment = time.time() if now is None else now
    ttl = ttl_seconds()
    for receipt in reversed(receipts):
        covered = receipt.get("files")
        if (
            receipt.get("context") != context
            or not isinstance(covered, dict)
            or moment - float(receipt.get("at", 0)) > ttl
        ):
            continue
        if all(covered.get(name) == digest for name, digest in current.items()):
            return receipt
    return None


def record(repo: Path, files: Sequence[str], hashes_before: dict[str, str], context_before: str | None) -> bool:
    """Store a passing run; refuse when a scope file or the context changed while it ran."""
    if not files or not enabled() or context_before is None or scope_hashes(repo, files) != hashes_before:
        return False
    path = _store_path(repo)
    if path is None or context_hash(repo) != context_before:
        return False
    receipts = [
        item
        for item in _load(path)
        if not (item.get("context") == context_before and item.get("files") == hashes_before)
    ]
    receipts.append({"context": context_before, "files": hashes_before, "at": time.time()})
    payload = {"version": _VERSION, "receipts": receipts[-_KEEP:]}
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".quick-check.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, sort_keys=True)
        temporary.replace(path)
    except OSError:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink()
        return False
    return True
