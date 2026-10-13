"""Monthly restore of the pinned critical sources the rotating offsite test cannot cover.

The rotating test (backup_offsite_restore_test) restores small repository sources and
skips guest streams and anything over its size cap. Two sources are too important to
wait for a rotation that never reaches them, so every monthly run restores them too:

- ``pve-host-files`` (vault identity, VM 120 config and snippets): a small tar stream.
  It is restored from both the offsite and the local repository, the two copies must be
  byte-identical, and every captured path must be in the archive with readable content.
- ``ominull-production-state`` (OmniNull hub vzdump tar, ~23 GB): the archive is
  streamed from the local repository under a fixed deadline. Its SHA-256 and size must match
  the capture manifest, every path the capture verified must be a regular file in it,
  and the hub and response-authority databases must pass SQLite quick_check. The
  offsite copy is checked by listing (same size), since a full offsite read each month
  would download the whole archive.

Only names, sizes and verdicts are recorded; restored contents stay in disposable
scratch and are removed with it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import shutil
import sqlite3
import tarfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import IO, Any

from ..storage import backups as backup_store
from ..utils.transient_scratch import ensure_scratch_capacity, restore_scratch

METHOD = "monthly-pinned-restore"
HOST_FILES = "pve-host-files"
HUB_STATE = "ominull-production-state"
PINNED_SOURCES = (HOST_FILES, HUB_STATE)
_SAFE_PATH = re.compile(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
_HUB_DATABASES = ("var/lib/ominull/ominull.db", "var/lib/ominull-response-authority/authority.db")
_CHECK_SECONDS = 20 * 60  # each database; the hub DB is ~20 GB
_STREAM_SECONDS = 45 * 60  # ~23 GB from the local repository disk; past this the drill fails


def pinned_point(source_id: str) -> dict[str, Any] | None:
    """Latest completed backup with both repository snapshots and a verified offsite copy."""
    rows, _ = backup_store.list_backups(source_id=source_id, limit=20)
    for row in sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True):
        verification = row.get("verification_json") or {}
        if row.get("status") != "completed" or (verification.get("offsite") or {}).get("status") != "verified":
            continue
        if verification.get("snapshot_id") and verification.get("remote_snapshot_id"):
            return row
    return None


def pinned_selection(sources: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    selected = []
    for source in sources:
        if source.get("id") in PINNED_SOURCES and source.get("enabled"):
            point = pinned_point(str(source["id"]))
            if point is not None:
                selected.append((source, point))
    return selected


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700)
    return path


def _read_all(stream: IO[bytes] | None) -> int:
    if stream is None:
        return -1
    total = 0
    while chunk := stream.read(1024 * 1024):
        total += len(chunk)
    return total


def check_tar_paths(archive: Path, paths: list[str], *, compressed: bool) -> dict[str, Any]:
    """Each captured path must be in the archive as a file, or a directory holding at least one non-empty file;
    every regular member must read back completely."""
    opener = gzip.open if compressed else open
    found: dict[str, dict[str, int]] = {path.strip("/"): {"files": 0, "bytes": 0} for path in paths}
    with opener(archive, "rb") as raw, tarfile.open(fileobj=raw, mode="r|") as tar:
        for member in tar:
            name = member.name.removeprefix("./").rstrip("/")
            owner = next((path for path in found if name == path or name.startswith(f"{path}/")), None)
            if owner is None or not member.isreg():
                continue
            read = _read_all(tar.extractfile(member))
            if read != member.size:
                raise RuntimeError(f"Archive member {name} reads back short")
            if member.size > 0:
                found[owner]["files"] += 1
                found[owner]["bytes"] += member.size
    missing = sorted(path for path, seen in found.items() if seen["files"] == 0)
    return {"paths": found, "missing": missing}


def restore_host_files(point: Mapping[str, Any]) -> dict[str, Any]:
    from .backup_proxmox import restore_stream_isolated

    verification = point.get("verification_json") or {}
    capture = verification.get("capture") or {}
    if capture.get("kind") != "proxmox-files" or not capture.get("paths"):
        raise RuntimeError("Pinned host-files backup is not a recorded Proxmox file capture")
    expected = int(capture.get("stream_bytes") or 0)
    with restore_scratch("st-monthly-pinned-", required_bytes=2 * expected + 1024**2) as scratch:
        remote = restore_stream_isolated(dict(point), _private_dir(scratch / "remote"), remote=True)
        local = restore_stream_isolated(dict(point), _private_dir(scratch / "local"))
        remote_file, local_file = Path(remote["payload_file"]), Path(local["payload_file"])
        identical = _sha256(remote_file) == _sha256(local_file)
        contents = check_tar_paths(remote_file, [str(path) for path in capture["paths"]], compressed=bool(capture.get("compressed")))
    return {"ok": identical and not contents["missing"], "method": METHOD, "remote": True, "format": "proxmox-files",
            "backup_id": point["id"], "remote_snapshot_id": verification["remote_snapshot_id"], "size_bytes": expected,
            "copies_identical": identical, "reference": "independent local repository", **contents}


class _HashingReader:
    """Counts and hashes everything tarfile reads from the stream."""

    def __init__(self, raw: IO[bytes]) -> None:
        self.raw, self.digest, self.bytes = raw, hashlib.sha256(), 0

    def read(self, size: int = -1) -> bytes:
        data = self.raw.read(size)
        self.digest.update(data)
        self.bytes += len(data)
        return data

    def drain(self) -> None:
        while self.read(1024 * 1024):
            pass


def _manifest_paths(manifest: Mapping[str, Any], key: str, *, allow_empty: bool = False) -> list[str]:
    values = manifest.get(key)
    if not isinstance(values, list) or not (values or allow_empty):
        raise RuntimeError(f"Capture manifest has no {key}")
    paths = [str(value) for value in values]
    if any(not _SAFE_PATH.fullmatch(path) or ".." in path.split("/") for path in paths):
        raise RuntimeError("Capture manifest names an unsafe path")
    return paths


def _quick_check(database: Path) -> dict[str, Any]:
    deadline = time.monotonic() + _CHECK_SECONDS
    connection = sqlite3.connect(str(database))
    try:
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 100_000)
        result = [row[0] for row in connection.execute("PRAGMA quick_check")]
        tables = connection.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    finally:
        connection.close()
    return {"ok": result == ["ok"] and tables > 0, "tables": tables, **({} if result == ["ok"] else {"quick_check": result[:5]})}


def _ls_size(adapter: Any, snapshot: str, path: str, *, remote: bool) -> int | None:
    listing = adapter._run(adapter._command("ls", snapshot, path, remote=remote), phase="verification", timeout=300)
    nodes = [json.loads(line) for line in listing.stdout.splitlines() if line.strip().startswith("{")]
    node = next((item for item in nodes if item.get("path") == path and item.get("type") == "file"), None)
    return int(node["size"]) if node and node.get("size") is not None else None


def restore_hub_state(point: Mapping[str, Any]) -> dict[str, Any]:
    from .backup_repository_runtime import (
        _approved_key_directory,
        _assert_repository_identity,
        _backup_environment,
    )
    from .backup_restic import ResticAdapter, ResticConfig, repository_lock

    verification = point.get("verification_json") or {}
    config = ResticConfig.from_env(_backup_environment(dict(point)))
    adapter = ResticAdapter(config)
    _approved_key_directory(config)
    _assert_repository_identity(adapter, verification, remote=True)
    _assert_repository_identity(adapter, verification)
    snapshot, remote_snapshot = str(verification["snapshot_id"]), str(verification["remote_snapshot_id"])
    started = time.monotonic()
    with restore_scratch("st-monthly-pinned-manifest-", required_bytes=1024**2) as small:
        target = _private_dir(small / "manifest")
        restored = adapter.restore(snapshot, target, include=["manifest.json"])
        root = Path(restored["payload_root"])
        manifest = json.loads((root / "manifest.json").read_text())
        payload_path = "/" + root.relative_to(target).as_posix()
    if manifest.get("source_id") != HUB_STATE or not re.fullmatch(r"[a-f0-9]{64}", str(manifest.get("sha256") or "")):
        raise RuntimeError("Capture manifest does not describe the hub state archive")
    archive_name = Path(str(manifest.get("archive_path") or "")).name
    if not _SAFE_PATH.fullmatch(archive_name) or "/" in archive_name:
        raise RuntimeError("Capture manifest names an unsafe archive")
    required = _manifest_paths(manifest, "required_paths_verified")
    wal = _manifest_paths(manifest, "wal_paths_verified", allow_empty=True)  # absent after a clean checkpoint
    wanted = set(required) | set(wal)
    size = int(manifest.get("size_bytes") or 0)
    archive_path = f"{payload_path}/{archive_name}"
    sizes: dict[str, int] = {}
    reader: _HashingReader | None = None
    # Only the databases and their WAL go to disk (quick_check needs files); every other member, keys included, is
    # read and counted in memory, so a crash never leaves production keys in scratch.
    on_disk = {path for path in wanted if path in _HUB_DATABASES or path.removesuffix("-wal") in _HUB_DATABASES}
    with restore_scratch("st-monthly-pinned-", required_bytes=0) as scratch:
        files = _private_dir(scratch / "files")

        def consume(stream: IO[bytes]) -> None:
            nonlocal reader
            reader = _HashingReader(stream)
            with tarfile.open(fileobj=reader, mode="r|") as tar:  # type: ignore[call-overload]
                for member in tar:
                    name = member.name.removeprefix("./")
                    if name not in wanted or not member.isreg() or name in sizes:
                        continue
                    source = tar.extractfile(member)
                    if name in on_disk:
                        ensure_scratch_capacity(scratch, member.size)
                        destination = files / name
                        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                        with destination.open("xb") as out:
                            destination.chmod(0o600)
                            shutil.copyfileobj(source, out, 1024 * 1024)
                        read = destination.stat().st_size
                    else:
                        read = _read_all(source)
                    if read != member.size:
                        raise RuntimeError(f"Archive member {name} reads back short")
                    sizes[name] = member.size
            reader.drain()

        with repository_lock(config):
            remote_size = _ls_size(adapter, remote_snapshot, archive_path, remote=True)
            # The owned runner reaps the process group on the deadline or a cancellation and polls scratch capacity,
            # so a stalled disk can never hold the pair lock past _STREAM_SECONDS.
            adapter._run(adapter._command("dump", snapshot, archive_path), phase="restore", stdout_sink=consume,
                         timeout=_STREAM_SECONDS, text=False)
        assert reader is not None
        missing = sorted(wanted - set(sizes))
        empty = sorted(path for path in required if sizes.get(path) == 0)
        databases = {path: _quick_check(files / path) for path in _HUB_DATABASES if path in sizes}
    archive_ok = reader.bytes == size and reader.digest.hexdigest() == manifest["sha256"]
    ok = (archive_ok and remote_size == size and not missing and not empty and len(databases) == len(_HUB_DATABASES)
          and all(item["ok"] for item in databases.values()))
    return {"ok": ok, "method": METHOD, "remote": False, "scope": "local repository restore + offsite listing",
            "format": "vzdump-lxc-tar", "backup_id": point["id"],
            "snapshot_id": snapshot, "archive": {"bytes": reader.bytes, "expected_bytes": size, "sha256_matches": archive_ok},
            "remote_listing": {"size_bytes": remote_size, "matches": remote_size == size},
            "files": {"required": len(required), "restored": len(sizes), "missing": missing, "empty": empty},
            "databases": databases, "duration_ms": int((time.monotonic() - started) * 1000)}


def restore_test_pinned(source: Mapping[str, Any], point: Mapping[str, Any]) -> dict[str, Any]:
    source_id = str(source["id"])
    started = time.monotonic()
    if source_id == HOST_FILES:
        evidence = restore_host_files(point)
    elif source_id == HUB_STATE:
        evidence = restore_hub_state(point)
    else:
        raise RuntimeError(f"{source_id} is not a pinned restore source")
    evidence.setdefault("duration_ms", int((time.monotonic() - started) * 1000))
    return evidence
