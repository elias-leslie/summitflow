"""Explicit, retained-backup page-size migration for the standalone monitor store.

Only the managed service lifecycle may call this module, after stopping the sole
collector writer. The maintenance lock excludes the monitor's managed readers.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TABLE_KEYS = {
    "meta": "key",
    "samples": "id",
    "events": "id",
    "host_rollups": "bucket_start_ns",
}
TARGET_PAGE_SIZE = 512
MIN_FREE_BYTES = 1024 * 1024 * 1024  # Match the collector's retention headroom.


class MonitorMigrationDeferred(RuntimeError):
    """No database conversion began; normal collector operation may resume."""


class MonitorMigrationFailed(RuntimeError):
    """Conversion may have begun; retain artifacts and leave the writer stopped."""


@dataclass(frozen=True)
class MigrationResult:
    status: str
    receipt: Path | None = None


def _pragma(connection: sqlite3.Connection, name: str) -> Any:
    return _single(connection, f"PRAGMA {name}")[0]


def _single(connection: sqlite3.Connection, query: str) -> tuple[Any, ...]:
    with closing(connection.execute(query)) as cursor:
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"SQLite query returned no row: {query}")
        return row


def _fingerprint(connection: sqlite3.Connection) -> dict[str, Any]:
    if _single(connection, "PRAGMA integrity_check") != ("ok",):
        raise ValueError("SQLite integrity_check failed")
    with closing(connection.execute("PRAGMA foreign_key_check")) as cursor:
        if cursor.fetchone() is not None:
            raise ValueError("SQLite foreign_key_check failed")
    with closing(connection.execute(
        "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )) as cursor:
        tables = {str(row[0]) for row in cursor}
    if tables != TABLE_KEYS.keys():
        raise ValueError(f"Unexpected monitor schema tables: {sorted(tables)}")
    result: dict[str, Any] = {}
    schema = hashlib.sha256()
    with closing(connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"
    )) as cursor:
        for row in cursor:
            _hash_row(schema, row)
    result["schema_sha256"] = schema.hexdigest()
    result["user_version"] = _pragma(connection, "user_version")
    for table, key in TABLE_KEYS.items():
        digest = hashlib.sha256()
        count = 0
        with closing(connection.execute(f'SELECT * FROM "{table}" ORDER BY "{key}"')) as cursor:
            for row in cursor:
                _hash_row(digest, row)
                count += 1
        result[table] = {"count": count, "sha256": digest.hexdigest()}
    return result


def _hash_row(digest: Any, row: tuple[Any, ...]) -> None:
    for value in row:
        if value is None:
            kind, encoded = b"n", b""
        elif isinstance(value, bytes):
            kind, encoded = b"b", value
        elif isinstance(value, str):
            kind, encoded = b"s", value.encode("utf-8")
        elif isinstance(value, int):
            kind, encoded = b"i", str(value).encode("ascii")
        else:
            kind, encoded = b"f", repr(value).encode("ascii")
        digest.update(kind)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    digest.update(b"\xff")


def _write_receipt(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_name(".receipt-next")
    with temporary.open("x", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(data, stream, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_dir(path.parent)


def _fsync_dir(path: Path) -> None:
    directory = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _owner_file(path: Path) -> None:
    try:
        owner_file = not path.is_symlink() and path.is_file() and path.stat().st_uid == os.getuid()
    except OSError as exc:
        raise MonitorMigrationDeferred(f"monitor database unavailable: {exc}") from exc
    if not owner_file:
        raise MonitorMigrationDeferred("monitor database is not an owner-owned regular file")
    if path.stat().st_mode & 0o077:
        raise MonitorMigrationDeferred("monitor database permissions are not owner-only")


def update_restart_receipt(path: Path, *, status: str) -> None:
    """Record the managed start result after a fully verified conversion."""
    if status not in {"succeeded", "collector_restart_failed"}:
        raise ValueError("unsupported migration restart status")
    receipt = json.loads(path.read_text())
    if receipt.get("status") != "converted_restart_pending":
        raise ValueError("migration receipt is not waiting for collector restart")
    receipt.update(status=status, restart_checked_at=time.time())
    _write_receipt(path, receipt)


def retain_restart_interlock(state_dir: Path, receipt_path: Path) -> None:
    """Block automatic retries when a converted collector fails its first start."""
    marker = state_dir / "migration.interlock"
    with marker.open("x", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(str(receipt_path) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(state_dir)


def _pending_restart_receipt(state_dir: Path) -> Path | None:
    root = state_dir / "migrations"
    if not root.is_dir():
        return None
    for path in sorted(root.glob("page512-*/receipt.json"), reverse=True):
        try:
            if json.loads(path.read_text()).get("status") == "converted_restart_pending":
                return path
        except (OSError, ValueError):
            continue
    return None


def migrate_stopped_store(state_dir: Path) -> MigrationResult:
    """Convert a stopped 1024-byte store; caller owns stop/resume decisions.

    No SQLite mutation occurs before the backup and content fingerprint match.
    A failure after journal conversion begins is a hard stop for manual recovery.
    """
    try:
        owner_state = (not state_dir.is_symlink() and state_dir.is_dir()
                       and state_dir.stat().st_uid == os.getuid()
                       and not state_dir.stat().st_mode & 0o077)
    except OSError as exc:
        raise MonitorMigrationDeferred(f"monitor state directory unavailable: {exc}") from exc
    if not owner_state:
        raise MonitorMigrationDeferred("monitor state directory is not owner-only")
    if (state_dir / "migration.interlock").exists() or (state_dir / "migration.interlock").is_symlink():
        raise MonitorMigrationFailed("existing monitor migration interlock requires manual recovery")
    db = state_dir / "monitor.sqlite3"
    if not db.exists():
        return MigrationResult("absent")
    _owner_file(db)
    collector_descriptor = _acquire_owner_lock(state_dir / "collector.lock", "collector")
    try:
        maintenance_descriptor = _acquire_owner_lock(state_dir / "maintenance.lock", "maintenance")
        try:
            if (state_dir / "migration.interlock").exists() or (state_dir / "migration.interlock").is_symlink():
                raise MonitorMigrationFailed("existing monitor migration interlock requires manual recovery")
            return _migrate_locked(db, state_dir)
        finally:
            os.close(maintenance_descriptor)
    finally:
        os.close(collector_descriptor)


def _acquire_owner_lock(path: Path, name: str) -> int:
    if path.is_symlink():
        raise MonitorMigrationDeferred(f"monitor {name} lock is a symlink")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise MonitorMigrationDeferred(f"monitor {name} lock unavailable: {exc}") from exc
    try:
        lock_stat = os.fstat(descriptor)
        if lock_stat.st_uid != os.getuid() or lock_stat.st_mode & 0o077:
            raise MonitorMigrationDeferred(f"monitor {name} lock is not owner-only")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MonitorMigrationDeferred(f"monitor {name} lock is active; retry later") from exc
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _migrate_locked(db: Path, state_dir: Path) -> MigrationResult:
    try:
        original = sqlite3.connect(db, timeout=0.0)
    except sqlite3.Error as exc:
        raise MonitorMigrationDeferred(f"monitor database unavailable: {exc}") from exc
    mutated = False
    receipt_path: Path | None = None
    receipt: dict[str, Any] | None = None
    try:
        original.execute("PRAGMA synchronous=FULL")
        page_size = _pragma(original, "page_size")
        if page_size == TARGET_PAGE_SIZE:
            pending = _pending_restart_receipt(state_dir)
            if pending is not None:
                try:
                    pending_data = json.loads(pending.read_text())
                    valid = (_pragma(original, "journal_mode") == "wal"
                             and _pragma(original, "synchronous") == 2
                             and _pragma(original, "auto_vacuum") == 2
                             and _fingerprint(original) == pending_data["after"])
                except (OSError, sqlite3.Error, ValueError, KeyError):
                    valid = False
                if not valid:
                    try:
                        retain_restart_interlock(state_dir, pending)
                    except OSError as exc:
                        raise MonitorMigrationFailed(
                            f"pending monitor conversion verification failed and recovery interlock could not be written: {pending}"
                        ) from exc
                    raise MonitorMigrationFailed(
                        f"pending monitor conversion no longer matches verified receipt: {pending}"
                    )
                return MigrationResult("converted_restart_pending", pending)
            return MigrationResult("already_current")
        if page_size != 1024 or str(_pragma(original, "journal_mode")).lower() != "wal":
            raise MonitorMigrationDeferred("monitor store is not the expected 1024-byte WAL database")
        before = _fingerprint(original)
        if _single(original, "SELECT value FROM meta WHERE key='schema_version'") != ("1",):
            raise MonitorMigrationDeferred("monitor store schema version is unsupported")
        wal = Path(f"{db}-wal")
        size = db.stat().st_size + (wal.stat().st_size if wal.exists() else 0)
        # SQLite VACUUM can require up to twice the database size; retain a
        # complete online backup alongside the conversion working space.
        if shutil.disk_usage(state_dir).free < MIN_FREE_BYTES + 3 * size:
            raise MonitorMigrationDeferred("insufficient free space for backup and VACUUM")
        artifact_dir = state_dir / "migrations" / f"page512-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        artifact_dir.mkdir(parents=True, mode=0o700)
        artifact_dir.chmod(0o700)
        _fsync_dir(artifact_dir.parent)
        _fsync_dir(state_dir)
        backup_path = artifact_dir / "monitor.sqlite3.backup"
        receipt_path = artifact_dir / "receipt.json"
        receipt = {"schema": 1, "status": "backing_up", "source": str(db),
                   "backup": str(backup_path), "started_at": time.time(),
                   "old_page_size": page_size, "target_page_size": TARGET_PAGE_SIZE,
                   "before": before}
        _write_receipt(receipt_path, receipt)
        backup_fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(backup_fd)
        with closing(sqlite3.connect(backup_path)) as backup:
            backup.execute("PRAGMA synchronous=FULL")
            original.backup(backup)
        backup_path.chmod(0o600)
        with closing(sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)) as backup:
            if _fingerprint(backup) != before:
                raise MonitorMigrationDeferred("monitor backup verification mismatch")
        # Flush WAL before switching journaling mode. A busy checkpoint means
        # an unmanaged reader remains; no page-size change has occurred.
        checkpoint = _single(original, "PRAGMA wal_checkpoint(TRUNCATE)")
        if checkpoint[0] != 0:
            raise MonitorMigrationDeferred("monitor WAL checkpoint blocked by another reader")
        interlock = state_dir / "migration.interlock"
        if interlock.exists() or interlock.is_symlink():
            raise MonitorMigrationDeferred("monitor migration interlock already exists")
        stream = interlock.open("x", encoding="utf-8")
        mutated = True  # A surviving marker must never be classified as safe to resume.
        with stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(str(receipt_path) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_dir(state_dir)
        receipt["status"] = "conversion_started"
        _write_receipt(receipt_path, receipt)
        mode = str(_pragma(original, "journal_mode=DELETE")).lower()
        if mode != "delete":
            raise ValueError(f"journal mode did not become DELETE: {mode}")
        original.execute(f"PRAGMA page_size={TARGET_PAGE_SIZE}")
        original.execute("PRAGMA auto_vacuum=INCREMENTAL")
        original.execute("VACUUM")
        if _pragma(original, "page_size") != TARGET_PAGE_SIZE:
            raise ValueError("page size did not become 512")
        if _pragma(original, "auto_vacuum") != 2 or _fingerprint(original) != before:
            raise ValueError("converted monitor store verification mismatch")
        mode = str(_pragma(original, "journal_mode=WAL")).lower()
        if mode != "wal":
            raise ValueError(f"journal mode did not return to WAL: {mode}")
        original.execute("PRAGMA synchronous=FULL")
        if _pragma(original, "synchronous") != 2 or _fingerprint(original) != before:
            raise ValueError("final monitor store verification mismatch")
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{db}{suffix}")
            if candidate.exists():
                candidate.chmod(0o600)
        receipt.update(status="converted_restart_pending", converted_at=time.time(),
                       new_page_size=TARGET_PAGE_SIZE, after=_fingerprint(original))
        _write_receipt(receipt_path, receipt)
        interlock.unlink()
        _fsync_dir(state_dir)
        return MigrationResult("converted_restart_pending", receipt_path)
    except MonitorMigrationDeferred as exc:
        if receipt_path is not None and receipt is not None and not mutated:
            receipt.update(status="deferred_before_conversion", deferred_at=time.time(), error=str(exc))
            with suppress(OSError):
                _write_receipt(receipt_path, receipt)
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        if mutated:
            if receipt_path is not None and receipt is not None:
                receipt.update(status="failed_after_mutation", failed_at=time.time(), error=str(exc))
                with suppress(OSError):
                    _write_receipt(receipt_path, receipt)
            raise MonitorMigrationFailed(
                f"monitor conversion stopped after mutation; inspect retained backup and receipt: {receipt_path}"
            ) from exc
        raise MonitorMigrationDeferred(f"monitor migration deferred before conversion: {exc}") from exc
    finally:
        original.close()
