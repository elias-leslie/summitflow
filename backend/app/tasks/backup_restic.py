"""Bounded Restic repositories; callers own capture, durable state, and scheduling.

The payload must be a validated, private tree at a stable absolute path. Keep
the returned local snapshot before calling ``sync``. Its repository-wide state
must be durably saved by ``persist`` before any remote copy can start. Remote
encrypted object IDs differ from local IDs: native copy reuses *blob* IDs, not
pack filenames. No plaintext password, OAuth bootstrap, archive cleanup, or
automatic retention is implemented here.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .backup_activity import BackupCancelled, check_backup_cancelled, run_bulk_process

RESTIC_VERSION = "0.19.1"
RCLONE_VERSION = "1.75.1"
DEFAULT_LOCAL_REPOSITORY = "/media/kasadis/Backups/davion-gem/restic"
_ID = re.compile(r"^[0-9a-f]{64}$")
_OBJECT = re.compile(r"^(?:data/[0-9a-f]{2}|index|snapshots|keys)/([0-9a-f]{64})$")
Runner = Callable[..., subprocess.CompletedProcess[Any]]
Persist = Callable[[dict[str, Any]], None]


class ResticError(RuntimeError):
    """An operation failed; messages deliberately exclude subprocess output."""


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Snapshot timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _id(value: str) -> str:
    if not _ID.fullmatch(value):
        raise ResticError("A full immutable Restic ID is required")
    return value


def _private_file(path: Path, directory: Path) -> None:
    """Check references without opening credentials or changing their modes."""
    root = directory.resolve(strict=True)
    if directory.is_symlink() or root.stat().st_mode & 0o077 or root.stat().st_uid != os.getuid():
        raise ResticError("Restic key directory must be private and not a symlink")
    if path.is_symlink() or path.resolve(strict=True).parent != root:
        raise ResticError("Credential references must be regular files in the private key directory")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise ResticError("Credential references must be private files owned by the current user")


@dataclass(frozen=True)
class ResticConfig:
    local_repository: Path
    local_password_file: Path
    key_directory: Path
    remote_repository: str | None = None
    remote_password_file: Path | None = None
    rclone_config: Path | None = None
    lock_directory: Path | None = None
    hostname: str = ""
    offsite_prune_qualified: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> ResticConfig:
        if env.get("BACKUP_ENGINE", "restic") != "restic":
            raise ResticError("Restic configuration requires BACKUP_ENGINE=restic")
        if not env.get("RESTIC_LOCAL_PASSWORD_FILE"):
            raise ResticError("RESTIC_LOCAL_PASSWORD_FILE is required")
        password = Path(env["RESTIC_LOCAL_PASSWORD_FILE"])
        return cls(
            local_repository=Path(env.get("RESTIC_LOCAL_REPOSITORY", DEFAULT_LOCAL_REPOSITORY)),
            local_password_file=password,
            key_directory=Path(env.get("RESTIC_KEY_DIRECTORY", str(password.parent))),
            remote_repository=env.get("RESTIC_REMOTE_REPOSITORY") or None,
            remote_password_file=Path(env["RESTIC_REMOTE_PASSWORD_FILE"]) if env.get("RESTIC_REMOTE_PASSWORD_FILE") else None,
            rclone_config=Path(env["RESTIC_RCLONE_CONFIG"]) if env.get("RESTIC_RCLONE_CONFIG") else None,
            lock_directory=Path(env["RESTIC_LOCK_DIRECTORY"]) if env.get("RESTIC_LOCK_DIRECTORY") else None,
            hostname=env.get("RESTIC_HOSTNAME") or socket.gethostname(),
            offsite_prune_qualified=env.get("RESTIC_OFFSITE_PRUNE_QUALIFIED", "false").lower() == "true",
        )

    def validate(self, *, remote: bool = False) -> None:
        if not self.local_repository.is_absolute() or not self.local_password_file.is_absolute():
            raise ResticError("Repository and credential paths must be absolute")
        _private_file(self.local_password_file, self.key_directory)
        if remote:
            if not self.remote_repository or not self.remote_password_file:
                raise ResticError("An independent remote repository and password-file reference are required")
            _private_file(self.remote_password_file, self.key_directory)
            if self.remote_repository.startswith("rclone:"):
                remote_path = self.remote_repository.removeprefix("rclone:")
                if not re.fullmatch(r"[A-Za-z0-9_-]+:[^\x00\r\n]+", remote_path):
                    raise ResticError("Remote repository must identify a bounded rclone folder")
                tail = remote_path.split(":", 1)[1]
                if tail.strip("/") in {"", "."} or ".." in tail.split("/"):
                    raise ResticError("The remote repository cannot be the remote root")
                if self.rclone_config is None:
                    raise ResticError("RESTIC_RCLONE_CONFIG is required; GNOME credentials are not used")
                _private_file(self.rclone_config, self.key_directory)
            elif not Path(self.remote_repository).is_absolute():
                raise ResticError("A fixture remote must be an absolute filesystem path")
            elif Path(self.remote_repository).resolve() == self.local_repository.resolve():
                raise ResticError("Local and remote repositories must be independent")


@contextmanager
def repository_lock(config: ResticConfig) -> Iterator[None]:
    """Pair-wide cancellable flock, retained alongside native Restic locks.

    All callers of a repository pair must use the same configured lock directory.
    Lock each repository separately so overlapping pairs cannot race locally.
    """
    directory = config.lock_directory or config.local_repository.parent / ".restic-locks"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ResticError("Repository lock directory must be private")
    repositories = {str(config.local_repository.resolve())}
    if config.remote_repository:
        repositories.add(config.remote_repository.rstrip("/"))
    descriptors: list[int] = []
    try:
        for repository in sorted(repositories):
            path = directory / (hashlib.sha256(repository.encode()).hexdigest() + ".lock")
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            descriptors.append(descriptor)
            while True:
                check_backup_cancelled()
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.1)
        yield
    finally:
        for descriptor in reversed(descriptors):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def select_retention(
    snapshots: Sequence[Mapping[str, Any]], retention_days: Mapping[str, int], *,
    now: datetime | None = None, pinned: Sequence[str] = (), pending: Sequence[str] = (),
    last_good: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Wall-clock expiry, always retaining three points and each source's last good."""
    current = now or _now()
    if current.tzinfo is None or any(days <= 0 for days in retention_days.values()):
        raise ResticError("Retention requires an aware clock and positive day windows")
    reasons: dict[str, set[str]] = {}
    groups: dict[str, list[tuple[datetime, str]]] = {}
    for snapshot in snapshots:
        snapshot_id = _id(str(snapshot["id"]))
        keep = reasons.setdefault(snapshot_id, set())
        tags = snapshot.get("tags") or []
        sources = [str(tag)[7:] for tag in tags if str(tag).startswith("source:")]
        try:
            created = _timestamp(str(snapshot["time"]))
        except (ValueError, KeyError):
            keep.add("unknown-time")
            continue
        if not sources:
            keep.add("unmanaged-source")
        for source in sources:
            groups.setdefault(source, []).append((created, snapshot_id))
            days = retention_days.get(source)
            if days is None:
                keep.add("unmanaged-source")
            elif created >= current - timedelta(days=days):
                keep.add("within-window")
    for group in groups.values():
        for _, snapshot_id in sorted(group, reverse=True)[:3]:
            reasons[snapshot_id].add("minimum-three")
    for label, ids in (("pinned", pinned), ("pending-offsite", pending), ("last-good", (last_good or {}).values())):
        for snapshot_id in ids:
            if snapshot_id in reasons:
                reasons[snapshot_id].add(label)
    return {
        "keep": sorted(snapshot_id for snapshot_id, why in reasons.items() if why),
        "delete": sorted(snapshot_id for snapshot_id, why in reasons.items() if not why),
        "reasons": {snapshot_id: sorted(why) for snapshot_id, why in reasons.items()},
        "selected_at": current.isoformat(),
    }


class ResticAdapter:
    """Standard Restic engine with a durable caller-owned verification journal."""

    def __init__(self, config: ResticConfig, *, runner: Runner | None = None) -> None:
        self.config = config
        self._runner = runner or run_bulk_process

    def _env(self) -> dict[str, str]:
        # Inline remote tokens, client credentials, roots, and backend options
        # may override rclone's approved file, just as inline Restic passwords
        # override repository references. Inherit neither tool's namespace.
        env = {key: value for key, value in os.environ.items() if not key.startswith(("RESTIC_", "RCLONE_"))}
        env["LC_ALL"] = "C"
        if self.config.rclone_config:
            env["RCLONE_CONFIG"] = str(self.config.rclone_config)
        return env

    def _run(self, command: list[str], *, phase: str, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        check_backup_cancelled()
        result = self._runner(command, env=self._env(), phase=phase, object_name="Restic repository", **kwargs)
        if result.returncode != 0:
            if command[0] == "restic" and result.returncode == 11:
                raise ResticError(f"restic {phase} failed to lock repository (exit 11); inspect active backups and stale native locks")
            raise ResticError(f"{command[0]} {phase} failed (exit {result.returncode}); inspect private operator diagnostics")
        return result

    def _command(self, *args: str, remote: bool = False, permanent_delete: bool = False, restore_cache: Path | None = None) -> list[str]:
        repository = self.config.remote_repository if remote else str(self.config.local_repository)
        password = self.config.remote_password_file if remote else self.config.local_password_file
        if not repository or not password:
            raise ResticError("Repository configuration is incomplete")
        command = ["restic", "--repo", repository, "--password-file", str(password), "--compression", "auto", "--json"]
        # Check creates and removes its own fresh cache. Disabling that cache
        # repeatedly downloads tree packs within the same check; --with-cache
        # would instead reuse old data and is deliberately never supplied.
        if restore_cache is not None:
            if not args or args[0] != "restore":
                raise ResticError("An operation cache is only supported for restore")
            command.extend(["--cache-dir", str(restore_cache)])
        elif not args or args[0] != "check":
            command.append("--no-cache")
        if permanent_delete and repository.startswith("rclone:"):
            if not self.config.offsite_prune_qualified:
                raise ResticError("Offsite permanent prune has not been explicitly qualified")
            command.extend(["-o", "rclone.args=serve restic --stdio --drive-use-trash=false"])
        return [*command, *args]

    def _json(self, *args: str, remote: bool = False, phase: str = "verification") -> Any:
        result = self._run(self._command(*args, remote=remote), phase=phase)
        try:
            return json.loads(result.stdout)
        except (ValueError, TypeError) as exc:
            raise ResticError("Restic returned invalid JSON") from exc

    def _repository(self, *, remote: bool = False) -> dict[str, Any]:
        value = self._json("cat", "config", remote=remote)
        if not isinstance(value, dict) or value.get("version") != 2:
            raise ResticError("A format-v2 repository is required; migrations are operator actions")
        _id(str(value.get("id", "")))
        return value

    def repository_identity(self, *, remote: bool = False) -> dict[str, Any]:
        """Authenticated repository identity for caller reference validation."""
        self.config.validate(remote=remote)
        with repository_lock(self.config):
            repository = self._repository(remote=remote)
            return {key: repository.get(key) for key in ("id", "version", "chunker_polynomial")}

    def readiness(self, *, local_only: bool = False) -> dict[str, Any]:
        """Read-only credential and pinned-binary checks, without secret contents."""
        try:
            self.config.validate(remote=not local_only)
            restic = self._run(["restic", "version"], phase="configuration")
            if not re.search(rf"\brestic {re.escape(RESTIC_VERSION)}\b", restic.stdout):
                raise ResticError(f"Restic {RESTIC_VERSION} is required")
            if not local_only and str(self.config.remote_repository).startswith("rclone:"):
                rclone = self._run(["rclone", "version"], phase="configuration")
                if not re.search(rf"\brclone v{re.escape(RCLONE_VERSION)}\b", rclone.stdout):
                    raise ResticError(f"rclone {RCLONE_VERSION} is required")
            return {"ready": True, "engine": "restic", "local_only": local_only}
        except (ResticError, OSError) as exc:
            return {"ready": False, "engine": "restic", "error": str(exc)}

    def initialize(self, *, local_only: bool = False) -> dict[str, Any]:
        """Explicitly initialize independent repositories; never repair/reinitialize."""
        self.config.validate(remote=not local_only)
        with repository_lock(self.config):
            for remote in ([False] if local_only else [False, True]):
                result = self._runner(self._command("cat", "config", remote=remote), env=self._env(), phase="configuration", object_name="Restic repository")
                if result.returncode == 10:
                    args = ["init", "--repository-version", "2"]
                    if remote:
                        args.extend(["--from-repo", str(self.config.local_repository), "--from-password-file", str(self.config.local_password_file), "--copy-chunker-params"])
                    self._run(self._command(*args, remote=remote), phase="configuration")
                elif result.returncode != 0:
                    raise ResticError(f"Repository open failed (exit {result.returncode}); initialization refused")
            local = self._repository()
            result = {"local_repository_id": local["id"], "format": "restic-v1"}
            if not local_only:
                remote_repo = self._repository(remote=True)
                if local["id"] == remote_repo["id"] or local.get("chunker_polynomial") != remote_repo.get("chunker_polynomial"):
                    raise ResticError("Copy requires independent repositories with identical chunker parameters")
                result["remote_repository_id"] = remote_repo["id"]
            return result

    def snapshots(self, *, source_id: str | None = None, remote: bool = False) -> list[dict[str, Any]]:
        self.config.validate(remote=remote)
        with repository_lock(self.config):
            return self._snapshots(source_id=source_id, remote=remote)

    def _snapshots(self, *, source_id: str | None = None, remote: bool = False) -> list[dict[str, Any]]:
        args = ["snapshots"]
        if source_id is not None:
            args.extend(["--tag", self._tag(source_id)])
        snapshots = self._json(*args, remote=remote)
        if not isinstance(snapshots, list):
            raise ResticError("Restic snapshot listing is invalid")
        for snapshot in snapshots:
            _id(str(snapshot.get("id", "")))
        return snapshots

    @staticmethod
    def _tag(source_id: str) -> str:
        if not source_id or not re.fullmatch(r"[A-Za-z0-9._-]+", source_id):
            raise ResticError("Source ID contains unsupported characters")
        return "source:" + source_id

    def save_payload(self, source_id: str, payload: Mapping[str, Any], *, parent_snapshot: str | None = None, defer_check: bool = False) -> dict[str, Any]:
        """Back up a stable, caller-validated staged tree; never a live source."""
        self.config.validate()
        root = Path(payload["snapshot_dir"])
        if not root.is_absolute() or root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
            raise ResticError("Prepared payload must be a private directory at a stable absolute path")
        if (payload.get("verification") or {}).get("verified") is not True:
            raise ResticError("Prepared payload has not passed capture validation")
        resolved = root.resolve()
        if self.config.local_repository.resolve().is_relative_to(resolved) or resolved.is_relative_to(self.config.local_repository.resolve()):
            raise ResticError("Payload and repository paths must not overlap")
        with repository_lock(self.config):
            repository = self._repository()
            previous = self._snapshots(source_id=source_id)
            suitable = [item for item in previous if item.get("paths") == [str(resolved)] and item.get("hostname") == (self.config.hostname or socket.gethostname())]
            if parent_snapshot is not None:
                _id(parent_snapshot)
                if not any(item["id"] == parent_snapshot for item in suitable):
                    raise ResticError("Explicit parent must match the source, hostname, and stable payload path")
            elif suitable:
                parent_snapshot = max(suitable, key=lambda item: _timestamp(item["time"]))["id"]
            args = ["backup", "--tag", self._tag(source_id), "--host", self.config.hostname or socket.gethostname()]
            args.extend(["--parent", parent_snapshot] if parent_snapshot else ["--force"])
            result = self._run(self._command(*args, "--", str(resolved)), phase="capture")
            try:
                messages = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
                summary = next(item for item in reversed(messages) if item.get("message_type") == "summary")
                snapshot_id = _id(str(summary["snapshot_id"]))
            except (ValueError, KeyError, StopIteration) as exc:
                raise ResticError("Restic did not return a completed snapshot summary") from exc
            if not defer_check:
                self._run(self._command("check"), phase="verification")
            logical = int(summary.get("total_bytes_processed", payload.get("total_bytes", 0)))
            stored = int(summary.get("data_added_packed", summary.get("data_added", 0)))
            return {
                **{key: value for key, value in payload.items() if key != "snapshot_dir"},
                "status": "completed", "format": "restic-v1", "source_id": source_id,
                "archive_name": snapshot_id, "repository_id": repository["id"], "snapshot_id": snapshot_id,
                "location": f"restic-v1:{repository['id']}:{snapshot_id}",
                "payload_path": str(resolved), "total_bytes": logical, "logical_bytes": logical,
                "data_added_bytes": int(summary.get("data_added", 0)), "stored_bytes": stored,
                "snapshot_metrics": {key: int(summary.get(key, 0)) for key in ("files_new", "files_changed", "files_unmodified", "dirs_new", "dirs_changed", "dirs_unmodified")},
                "parent_snapshot_id": parent_snapshot,
                "verification": {
                    "verified": True, "format": "restic-v1", "method": "restic-backup-and-consistent-capture" if defer_check else "restic-backup-and-structural-check",
                    "repository_id": repository["id"], "snapshot_id": snapshot_id,
                    "payload_path": str(resolved), "structural_check_at": None if defer_check else _now().isoformat(),
                    "structural_check_pending": defer_check,
                    "payload_read_verified": False, "capture": dict(payload["verification"]),
                    "offsite": {"status": "pending"},
                },
            }

    def _inventory(self) -> dict[str, dict[str, Any]]:
        remote = self.config.remote_repository or ""
        if remote.startswith("rclone:"):
            command = ["rclone", "lsjson", remote.removeprefix("rclone:"), "--recursive", "--files-only", "--config", str(self.config.rclone_config)]
            result = self._run(command, phase="verification")
            try:
                entries = json.loads(result.stdout)
            except ValueError as exc:
                raise ResticError("Remote inventory JSON is invalid") from exc
            if not isinstance(entries, list):
                raise ResticError("Remote inventory must be a list")
        else:
            directory = Path(remote)
            entries = []
            for path in directory.rglob("*"):
                if path.is_symlink():
                    raise ResticError("Fixture repository must not contain symlinks")
                if path.is_file():
                    entries.append({"Path": str(path.relative_to(directory)), "Size": path.stat().st_size, "ID": str(path.relative_to(directory))})
        inventory: dict[str, dict[str, Any]] = {}
        for entry in entries:
            path = str(entry.get("Path", ""))
            if not _OBJECT.fullmatch(path):
                continue  # Config is authenticated by repository open; locks are mutable.
            if path in inventory or entry.get("IsDir") or not entry.get("ID"):
                raise ResticError("Remote object identity is ambiguous")
            if path.startswith("data/") and path.split("/")[1] != Path(path).name[:2]:
                raise ResticError("Remote pack path does not match its immutable ID")
            inventory[path] = entry
        return inventory

    def _verify_object(self, path: str, entry: Mapping[str, Any], *, allow_download: bool) -> dict[str, Any]:
        expected = _OBJECT.fullmatch(path)
        if not expected:
            raise ResticError("Only hash-addressed immutable repository objects may be verified")
        remote = self.config.remote_repository or ""
        observed: str | None = None
        method = "provider-sha256"
        storage_id = str(entry["ID"])
        if remote.startswith("rclone:"):
            target = remote.removeprefix("rclone:").rstrip("/") + "/" + path
            # A fresh process/stat invokes Drive NewObject -> Files API fields
            # including sha256Checksum (rclone 1.75.1), not an upload cache/MD5.
            result = self._run(["rclone", "lsjson", target, "--stat", "--files-only", "--hash-type", "SHA-256", "--config", str(self.config.rclone_config)], phase="verification")
            try:
                metadata = json.loads(result.stdout)
                if metadata.get("ID") != storage_id or metadata.get("IsDir") or int(metadata["Size"]) != int(entry["Size"]):
                    raise ResticError("Remote object identity or size changed during verification")
                hashes = metadata.get("Hashes") or {}
                observed = hashes.get("SHA-256") or hashes.get("SHA256") or hashes.get("sha256")
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ResticError("Fresh remote object metadata is invalid") from exc
            if not observed:
                if not allow_download:
                    raise ResticError("Previously verified object lost its provider SHA-256; payload recheck required")
                digest = hashlib.sha256()
                count = 0

                def consume(stream: Any) -> None:
                    nonlocal count
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        check_backup_cancelled()
                        digest.update(chunk)
                        count += len(chunk)

                self._run(["rclone", "cat", target, "--config", str(self.config.rclone_config)], phase="verification", stdout_sink=consume, text=False)
                if count != int(entry["Size"]):
                    raise ResticError("Downloaded remote object size changed")
                # Confirm storage ID again after the download; provider may
                # replace an object under the same visible filename.
                after = self._run(["rclone", "lsjson", target, "--stat", "--files-only", "--hash-type", "SHA-256", "--config", str(self.config.rclone_config)], phase="verification")
                after_metadata = json.loads(after.stdout)
                if after_metadata.get("ID") != storage_id or int(after_metadata.get("Size", -1)) != count:
                    raise ResticError("Remote object identity changed during download")
                after_hashes = after_metadata.get("Hashes") or {}
                after_hash = after_hashes.get("SHA-256") or after_hashes.get("SHA256") or after_hashes.get("sha256")
                if after_hash and after_hash.lower() != expected[1]:
                    raise ResticError("Immutable remote object SHA-256 mismatch after download")
                observed, method = digest.hexdigest(), "affected-object-download-sha256"
        else:
            digest = hashlib.sha256()
            with (Path(remote) / path).open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    check_backup_cancelled()
                    digest.update(chunk)
            observed, method = digest.hexdigest(), "fixture-object-sha256"
        if str(observed).lower() != expected[1]:
            raise ResticError("Immutable remote object SHA-256 mismatch")
        return {"id": storage_id, "size": int(entry["Size"]), "mod_time": entry.get("ModTime"), "method": method, "verified_at": _now().isoformat()}

    def sync(self, snapshot_id: str, *, state: Mapping[str, Any] | None = None, persist: Persist | None = None) -> dict[str, Any]:
        """Copy missing blobs, then reconcile *all* unknown objects on every retry.

        ``persist`` is mandatory: copy can finish before SQL/verification. The
        repository-wide journal is saved before copy; interrupted new objects
        are reconstructed from the next remote inventory even if copy skips.
        Persisted hash failures are never cleared merely by deduplicated copy.
        """
        _id(snapshot_id)
        self.config.validate(remote=True)
        if persist is None:
            raise ResticError("Offsite copy requires a durable repository-state callback")
        journal = copy.deepcopy(dict(state or {}))
        journal.setdefault("version", 1)
        journal.setdefault("verified_objects", {})
        journal.setdefault("pending_objects", [])
        journal.setdefault("mismatches", {})
        journal.setdefault("pending_snapshot_ids", [])
        journal.setdefault("remote_snapshots", {})
        if journal.get("version") != 1 or any(not isinstance(journal[key], dict) for key in ("verified_objects", "mismatches", "remote_snapshots")) or any(not isinstance(journal[key], list) for key in ("pending_objects", "pending_snapshot_ids")):
            raise ResticError("Unsupported offsite verification journal")
        for pending_id in journal["pending_snapshot_ids"]:
            _id(pending_id)
        for path in [*journal["verified_objects"], *journal["pending_objects"], *journal["mismatches"]]:
            if not isinstance(path, str) or not _OBJECT.fullmatch(path):
                raise ResticError("Verification journal contains an invalid immutable object path")

        def save() -> None:
            persist(copy.deepcopy(journal))

        with repository_lock(self.config):
            local = self._repository()
            if journal.get("local_repository_id") not in (None, local["id"]):
                raise ResticError("Verification journal belongs to a different local repository")
            journal["local_repository_id"] = local["id"]
            if snapshot_id not in journal["pending_snapshot_ids"]:
                journal["pending_snapshot_ids"].append(snapshot_id)
            journal.update(status="pending", copy_started_at=_now().isoformat())
            save()  # Must succeed before any remote mutation.
            try:
                remote = self._repository(remote=True)
                if journal.get("remote_repository_id") not in (None, remote["id"]):
                    raise ResticError("Verification journal belongs to a different remote repository")
                if local["id"] == remote["id"] or local.get("chunker_polynomial") != remote.get("chunker_polynomial"):
                    raise ResticError("Repositories are not independent with shared chunker parameters")
                journal["remote_repository_id"] = remote["id"]
                if (journal.get("maintenance") or {}).get("status") == "pending":
                    raise ResticError("Interrupted qualified maintenance must be reconciled before offsite copy")
                before = self._inventory()
                # Save discoveries before copy, including a previous interrupted
                # run that never reached its post-copy inventory checkpoint.
                unknown = set(before) - set(journal["verified_objects"])
                journal["pending_objects"] = sorted(set(journal["pending_objects"]) | unknown | set(journal["mismatches"]))
                save()
                args = ["copy", "--from-repo", str(self.config.local_repository), "--from-password-file", str(self.config.local_password_file), *journal["pending_snapshot_ids"]]
                self._run(self._command(*args, remote=True), phase="upload")
                after = self._inventory()
                journal["pending_objects"] = sorted(set(journal["pending_objects"]) | (set(after) - set(journal["verified_objects"])))
                journal["copy_completed_at"] = _now().isoformat()
                journal["new_object_bytes"] = sum(int(after[path]["Size"]) for path in set(after) - set(before))
                save()
                # Restic authenticates config and verifies structure. It does
                # not read every pack here; provider hashes cover ciphertext.
                self._run(self._command("check", remote=True), phase="verification")
                remote_snapshots = self._snapshots(remote=True)
                for pending_id in list(journal["pending_snapshot_ids"]):
                    matches = [item for item in remote_snapshots if item["id"] == pending_id or item.get("original") == pending_id]
                    if not matches:
                        raise ResticError("Pending snapshot is not present in the independent repository")
                    journal["remote_snapshots"][pending_id] = matches[0]["id"]
                pending = set(journal["pending_objects"])
                # The fresh inventory proves known-object presence and storage
                # identity without one rclone process per retained pack on each
                # source backup. Monthly buckets re-read old payload. Only new,
                # pending, mismatched, or changed objects need fresh SHA checks.
                for path in sorted(set(after) | pending | set(journal["verified_objects"])):
                    check_backup_cancelled()
                    try:
                        if path not in after:
                            raise ResticError("Previously recorded remote object is missing; qualified maintenance reconciliation required")
                        previous = journal["verified_objects"].get(path)
                        entry = after[path]
                        if previous and (previous.get("id") != entry["ID"] or previous.get("size") != int(entry["Size"]) or previous.get("mod_time") != entry.get("ModTime")):
                            pending.add(path)
                        if previous and path not in pending and path not in journal["mismatches"]:
                            previous["last_seen_at"] = _now().isoformat()
                            continue
                        evidence = self._verify_object(path, entry, allow_download=path in pending)
                    except ResticError as exc:
                        journal["mismatches"][path] = str(exc)
                        pending.add(path)
                        journal["pending_objects"] = sorted(pending)
                        save()
                        raise
                    journal["verified_objects"][path] = evidence
                    journal["mismatches"].pop(path, None)
                    pending.discard(path)
                journal["pending_objects"] = sorted(pending)
                if journal["mismatches"] or pending:
                    raise ResticError("Unresolved remote verification objects remain")
                journal.update(status="verified", verified_at=_now().isoformat(), structural_check_at=_now().isoformat(), pending_snapshot_ids=[])
                journal.pop("error", None)
                save()
                return {"status": "verified", "snapshot_id": snapshot_id, "remote_snapshot_id": journal["remote_snapshots"][snapshot_id], "remote_repository_id": remote["id"], "verification": {"verified": True, "offsite": {"status": "verified", "method": "restic-structure-and-immutable-sha256", "verified_at": journal["verified_at"], "object_count": len(after), "new_object_bytes": journal["new_object_bytes"]}}, "state": journal}
            except BackupCancelled:
                journal["status"] = "pending"
                save()
                raise
            except (ResticError, OSError, ValueError, TypeError) as exc:
                journal.update(status="failed" if journal["mismatches"] else "pending", error=str(exc))
                save()
                return {"status": journal["status"], "snapshot_id": snapshot_id, "verification": {"verified": False, "offsite": {"status": journal["status"], "error": str(exc)}}, "state": journal}

    def restore(self, snapshot_id: str, destination: Path, *, remote: bool = False, include: Sequence[str] = ()) -> dict[str, Any]:
        """Restore only into an existing private empty isolated directory."""
        _id(snapshot_id)
        self.config.validate(remote=remote)
        if not destination.is_absolute() or destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()) or destination.stat().st_mode & 0o077:
            raise ResticError("Restore destination must be an empty private absolute directory")
        if destination.resolve().is_relative_to(self.config.local_repository.resolve()) or self.config.local_repository.resolve().is_relative_to(destination.resolve()):
            raise ResticError("Restore destination and repository paths must not overlap")
        if self.config.remote_repository and not self.config.remote_repository.startswith("rclone:"):
            remote_path = Path(self.config.remote_repository).resolve()
            if destination.resolve().is_relative_to(remote_path) or remote_path.is_relative_to(destination.resolve()):
                raise ResticError("Restore destination and remote fixture paths must not overlap")
        with repository_lock(self.config):
            snapshots = [item for item in self._snapshots(remote=remote) if item["id"] == snapshot_id]
            if len(snapshots) != 1 or len(snapshots[0].get("paths") or []) != 1:
                raise ResticError("Restore requires one identifiable staged payload root")
            payload_path = Path(snapshots[0]["paths"][0])
            if not payload_path.is_absolute() or ".." in payload_path.parts:
                raise ResticError("Snapshot payload path is unsafe")
            args = ["restore", snapshot_id, "--target", str(destination), "--verify"]
            for path in include:
                if not path or Path(path).is_absolute() or ".." in Path(path).parts or any(char in path for char in "*?[]"):
                    raise ResticError("Restore include must be a literal path relative to the staged payload")
                args.extend(["--include", str(payload_path / path)])
            # Repeated tree reads may otherwise re-download remote metadata.
            # This cache starts empty, belongs only to this restore job, and
            # cannot reuse an existing cache or an earlier restore's metadata.
            with tempfile.TemporaryDirectory(prefix="restic-restore-cache-", dir=destination.parent) as cache:
                self._run(self._command(*args, remote=remote, restore_cache=Path(cache)), phase="restore")
            root = destination / payload_path.relative_to("/")
            if not root.is_dir() or root.is_symlink():
                raise ResticError("Restic did not materialize the expected payload root")
            if any(not (root / path).exists() for path in include):
                raise ResticError("A requested recovery file was not materialized")
            return {"status": "completed", "snapshot_id": snapshot_id, "destination": str(destination), "payload_root": str(root), "verification": {"verified": True, "method": "restic-restore-verify", "partial": bool(include)}}

    def check(self, *, remote: bool = False, monthly_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Structural daily check or deterministic n/30 payload check.

        A bucket advances only on success. Stale coverage is reported explicitly;
        thirty successful daily buckets cover pack[0] % 30, not random samples.
        The caller persists the returned state and controls the daily cadence.
        """
        self.config.validate(remote=remote)
        state = copy.deepcopy(dict(monthly_state or {}))
        monthly = monthly_state is not None
        bucket = int(state.get("next_bucket", 1))
        if not 1 <= bucket <= 30:
            raise ResticError("Monthly check bucket must be in 1..30")
        now = _now()
        coverage = state.setdefault("bucket_success_at", {})
        stale = [number for number in range(1, 31) if str(number) not in coverage or _timestamp(coverage[str(number)]) < now - timedelta(days=30)]
        with repository_lock(self.config):
            try:
                repository = self._repository(remote=remote)
                if state.get("repository_id") not in (None, repository["id"]):
                    raise ResticError("Monthly coverage belongs to a different repository")
                args = ["check"]
                if monthly:
                    args.append(f"--read-data-subset={bucket}/30")
                self._run(self._command(*args, remote=remote), phase="verification")
                if monthly:
                    coverage[str(bucket)] = now.isoformat()
                    state.update(repository_id=repository["id"], next_bucket=bucket % 30 + 1, successful_runs=int(state.get("successful_runs", 0)) + 1)
                    stale = [number for number in stale if number != bucket]
                return {"status": "verified", "verified": True, "method": "restic-monthly-bucket" if monthly else "restic-structural-check", "checked_at": now.isoformat(), "bucket": bucket if monthly else None, "stale_buckets": stale if monthly else [], "coverage_complete": monthly and not stale, "state": state}
            except ResticError as exc:
                return {"status": "failed", "verified": False, "error": str(exc), "bucket": bucket if monthly else None, "stale_buckets": stale if monthly else [], "state": state}

    def _maintenance_state(self, state: Mapping[str, Any], *, operation: str, persist: Persist, snapshot_ids: Sequence[str] = ()) -> dict[str, Any]:
        journal = copy.deepcopy(dict(state))
        repository = self._repository(remote=True)
        if journal.get("remote_repository_id") not in (None, repository["id"]):
            raise ResticError("Maintenance journal belongs to a different remote repository")
        journal["remote_repository_id"] = repository["id"]
        intent = journal.get("maintenance") or {}
        if intent.get("status") == "pending":
            if intent.get("operation") != operation:
                raise ResticError("A different interrupted maintenance operation must be resumed first")
            if intent.get("version") != 1 or not isinstance(intent.get("baseline_objects"), list) or not isinstance(intent.get("snapshot_ids"), list):
                raise ResticError("Interrupted maintenance has no valid durable authorization scope")
            for path in intent["baseline_objects"]:
                if not isinstance(path, str) or not _OBJECT.fullmatch(path):
                    raise ResticError("Interrupted maintenance object scope is invalid")
            for snapshot_id in intent["snapshot_ids"]:
                _id(snapshot_id)
            if operation == "prune" and intent["snapshot_ids"]:
                raise ResticError("Prune cannot authorize snapshot removal")
            return journal  # Retain the original durable intent, including its clock.
        inventory = self._inventory()
        if set(journal.get("verified_objects") or {}) - set(inventory):
            raise ResticError("Recorded objects are missing before maintenance; authorization refused")
        journal["maintenance"] = {
            "version": 1, "status": "pending", "operation": operation,
            "phase": "prepared", "started_at": _now().isoformat(), "baseline_objects": sorted(inventory),
            "snapshot_ids": sorted({_id(snapshot_id) for snapshot_id in snapshot_ids}),
            "physical_bytes_before": sum(int(entry["Size"]) for entry in inventory.values()),
        }
        persist(copy.deepcopy(journal))
        return journal

    def _reconcile_maintenance(self, journal: dict[str, Any], persist: Persist) -> None:
        """Reconcile durable scope and verify repacks before claiming completion."""
        repository = self._repository(remote=True)
        if journal.get("remote_repository_id") != repository["id"]:
            raise ResticError("Maintenance journal belongs to a different remote repository")
        self._run(self._command("check", remote=True), phase="verification")
        inventory = self._inventory()
        verified = journal.setdefault("verified_objects", {})
        mismatches = journal.setdefault("mismatches", {})
        pending = set(journal.get("pending_objects") or [])
        intent = journal["maintenance"]
        recorded = set(intent["baseline_objects"]) | set(verified) | pending | set(mismatches)
        removed = recorded - set(inventory)
        if intent["operation"] == "forget":
            allowed = {"snapshots/" + snapshot_id for snapshot_id in intent["snapshot_ids"]}
            remaining = allowed & set(inventory)
        elif intent["operation"] == "prune":
            allowed = {path for path in recorded if path.startswith(("data/", "index/"))}
            remaining = set()
        else:
            raise ResticError("Unknown maintenance operation")
        unexpected = removed - allowed
        if unexpected or remaining:
            for path in sorted(unexpected):
                mismatches[path] = "Object removal is outside the durable maintenance authorization scope"
            journal.update(status="failed", pending_objects=sorted(pending | unexpected))
            persist(copy.deepcopy(journal))
            raise ResticError("Maintenance removed unauthorized objects" if unexpected else "Authorized snapshots remain after forget")
        pending.difference_update(removed)
        pending.update(set(inventory) - set(verified))
        pending.update(set(mismatches) & set(inventory))
        for path, entry in inventory.items():
            previous = verified.get(path)
            if previous and (previous.get("id") != entry["ID"] or previous.get("size") != int(entry["Size"]) or previous.get("mod_time") != entry.get("ModTime")):
                pending.add(path)
        journal["pending_objects"] = sorted(pending)
        persist(copy.deepcopy(journal))  # Reconstructible scope precedes payload reads.
        for path in sorted(pending):
            check_backup_cancelled()
            try:
                evidence = self._verify_object(path, inventory[path], allow_download=True)
            except ResticError as exc:
                mismatches[path] = str(exc)
                journal.update(status="failed", pending_objects=sorted(pending))
                persist(copy.deepcopy(journal))
                raise
            verified[path] = evidence
            mismatches.pop(path, None)
            pending.remove(path)
        if set(mismatches) - removed:
            journal.update(status="failed", pending_objects=sorted(pending))
            persist(copy.deepcopy(journal))
            raise ResticError("Unresolved immutable-object mismatches remain after maintenance")
        for path in removed:
            verified.pop(path, None)
            mismatches.pop(path, None)
        if intent["operation"] == "forget":
            forgotten = set(intent["snapshot_ids"])
            journal["remote_snapshots"] = {local_id: remote_id for local_id, remote_id in (journal.get("remote_snapshots") or {}).items() if remote_id not in forgotten}
        journal["pending_objects"] = sorted(pending)
        journal["status"] = "pending" if journal.get("pending_snapshot_ids") else "verified"
        # A prepared prune may have crashed before its native command ran.
        # Safe reconciliation is distinct from observed native completion.
        completed = intent["operation"] == "forget" or intent.get("phase") == "command_completed"
        intent.update(status="completed" if completed else "reconciled", completed_at=_now().isoformat() if completed else None, retired_object_count=len(removed), repacked_objects_verified=True)
        journal.pop("error", None)
        persist(copy.deepcopy(journal))

    def quota_free_bytes(self) -> int | None:
        """Read provider-reported free bytes; unavailable quota is not headroom."""
        self.config.validate(remote=True)
        with repository_lock(self.config):
            return self._quota_free_bytes()

    def _quota_free_bytes(self) -> int | None:
        """Caller owns the repository lock, including post-prune observation."""
        remote = self.config.remote_repository or ""
        if not remote.startswith("rclone:"):
            return shutil.disk_usage(Path(remote)).free
        result = self._run(["rclone", "about", remote.removeprefix("rclone:"), "--json", "--config", str(self.config.rclone_config)], phase="configuration")
        try:
            free = json.loads(result.stdout).get("free")
            if free is None:
                return None
            if isinstance(free, bool) or not isinstance(free, int) or free < 0:
                raise ResticError("Provider free-space response is invalid")
            return free
        except (ValueError, TypeError, AttributeError) as exc:
            raise ResticError("Provider free-space JSON is invalid") from exc

    def physical_bytes(self, *, remote: bool = False) -> int:
        """Measure actual object storage, independently of retained logical size."""
        if remote:
            return sum(int(entry["Size"]) for entry in self._inventory().values())
        return sum(path.stat().st_size for path in self.config.local_repository.rglob("*") if path.is_file() and not path.is_symlink())

    def retention(self, retention_days: Mapping[str, int], *, remote: bool = False, pinned: Sequence[str] = (), pending: Sequence[str] = (), last_good: Mapping[str, str] | None = None, state: Mapping[str, Any] | None = None, persist: Persist | None = None, dry_run: bool = True) -> dict[str, Any]:
        """Preview by default; explicit scoped forgetting never invokes prune."""
        self.config.validate(remote=remote)
        if remote and not dry_run and not self.config.offsite_prune_qualified:
            raise ResticError("Offsite retention has not been explicitly qualified")
        if not dry_run and state is None:
            raise ResticError("Applying retention requires the repository verification journal")
        with repository_lock(self.config):
            journal = copy.deepcopy(dict(state or {}))
            pending_ids = set(pending) | set(journal.get("pending_snapshot_ids") or [])
            if remote:
                copied = journal.get("remote_snapshots") or {}
                pending_ids = {copied.get(snapshot_id, snapshot_id) for snapshot_id in pending_ids}
            snapshots = self._snapshots(remote=remote)
            if remote and (journal.get("pending_objects") or journal.get("mismatches")):
                pending_ids.update(item["id"] for item in snapshots)
            selection = select_retention(snapshots, retention_days, pinned=pinned, pending=sorted(pending_ids), last_good=last_good)
            resume = remote and not dry_run and (journal.get("maintenance") or {}).get("status") == "pending"
            if selection["delete"] or resume:
                if remote and not dry_run:
                    if persist is None:
                        raise ResticError("Remote retention requires durable maintenance checkpoints")
                    journal = self._maintenance_state(journal, operation="forget", persist=persist, snapshot_ids=selection["delete"])
                    selection["delete"] = list(journal["maintenance"]["snapshot_ids"])
                current = {snapshot["id"] for snapshot in snapshots}
                targets = [snapshot_id for snapshot_id in selection["delete"] if snapshot_id in current]
                args = ["forget", *targets]
                if dry_run:
                    args.append("--dry-run")
                # Always preview the exact immutable IDs before destructive forget.
                if targets and not dry_run:
                    self._run(self._command(*args, "--dry-run", remote=remote, permanent_delete=remote), phase="retention")
                if targets:
                    self._run(self._command(*args, remote=remote, permanent_delete=remote and not dry_run), phase="retention")
                if remote and not dry_run:
                    assert persist is not None
                    journal["maintenance"]["phase"] = "command_completed"
                    persist(copy.deepcopy(journal))
                    self._reconcile_maintenance(journal, persist)
            return {**selection, "dry_run": dry_run, "status": "preview" if dry_run else "completed", "state": journal}

    def prune(self, *, remote: bool = False, state: Mapping[str, Any] | None = None, persist: Persist | None = None, last_prune_at: str | None = None, available_bytes: int | None = None, minimum_headroom_bytes: int = 1024**3, dry_run: bool = True) -> dict[str, Any]:
        """Weekly independent maintenance, with preview, headroom, and 5% allowance.

        No forgetting occurs here. Remote permanent deletion requires the
        qualified configuration flag and a caller-provided quota-free budget.
        Never uses rclone purge/delete or global Drive trash cleanup.
        """
        self.config.validate(remote=remote)
        journal = copy.deepcopy(dict(state or {}))
        resume = remote and not dry_run and (journal.get("maintenance") or {}).get("status") == "pending"
        if resume and (journal.get("maintenance") or {}).get("operation") != "prune":
            return {"status": "skipped", "reason": "different-maintenance-operation-pending", "state": journal}
        if minimum_headroom_bytes <= 0 or (available_bytes is not None and (isinstance(available_bytes, bool) or not isinstance(available_bytes, int) or available_bytes < 0)):
            raise ResticError("Prune requires a positive headroom reserve and nonnegative free bytes")
        if not dry_run and state is None:
            return {"status": "skipped", "reason": "verification-journal-required"}
        if not resume and (journal.get("pending_snapshot_ids") or journal.get("pending_objects") or journal.get("mismatches")):
            return {"status": "skipped", "reason": "pending-verification"}
        if not resume and last_prune_at and _timestamp(last_prune_at) > _now() - timedelta(days=7):
            return {"status": "skipped", "reason": "weekly-cadence"}
        if remote and not self.config.offsite_prune_qualified:
            return {"status": "skipped", "reason": "offsite-not-qualified"}
        if remote and not dry_run and persist is None:
            return {"status": "skipped", "reason": "durable-maintenance-checkpoint-required"}
        free = available_bytes
        if free is None and not remote:
            free = shutil.disk_usage(self.config.local_repository).free
        if not resume and (free is None or free < minimum_headroom_bytes * 2):
            return {"status": "skipped", "reason": "insufficient-headroom"}
        with repository_lock(self.config):
            try:
                if resume:
                    assert persist is not None
                    journal = self._maintenance_state(journal, operation="prune", persist=persist)
                    command_completed = journal["maintenance"].get("phase") == "command_completed"
                    # First reconcile a completed native prune whose final state
                    # write was interrupted. Never rerun mutation to erase a
                    # recorded corruption before verification can see it.
                    self._reconcile_maintenance(journal, persist)
                    if command_completed:
                        after_bytes = self.physical_bytes(remote=True)
                        before_bytes = journal["maintenance"].get("physical_bytes_before")
                        return {"status": "completed", "dry_run": False, "resumed": True, "completed_at": journal["maintenance"]["completed_at"], "physical_bytes_before": before_bytes, "physical_bytes_after": after_bytes, "physical_bytes_confirmed": True, "reclaimed_bytes": max(0, before_bytes - after_bytes) if before_bytes is not None else None, "free_bytes": self._quota_free_bytes(), "state": journal}
                    # The crash may have preceded native mutation. Reconciliation
                    # verified the old intent; only a new saved intent may rerun
                    # prune, after checking currently available headroom.
                    if free is None or free < minimum_headroom_bytes * 2:
                        return {"status": "skipped", "reason": "insufficient-headroom", "state": journal}
                assert free is not None  # New mutation always passed the headroom gate.
                before_bytes = self.physical_bytes(remote=remote)
                self._run(self._command("check", remote=remote), phase="verification")
                args = ["prune", "--max-unused", "5%", "--max-repack-size", str(free - minimum_headroom_bytes)]
                self._run(self._command(*args, "--dry-run", remote=remote, permanent_delete=remote), phase="maintenance")
                if not dry_run:
                    if remote:
                        assert persist is not None
                        journal = self._maintenance_state(journal, operation="prune", persist=persist)
                    self._run(self._command(*args, remote=remote, permanent_delete=remote), phase="maintenance")
                    if remote:
                        assert persist is not None
                        journal["maintenance"]["phase"] = "command_completed"
                        persist(copy.deepcopy(journal))
                        self._reconcile_maintenance(journal, persist)
                after_bytes = self.physical_bytes(remote=remote)
                observed_free = self._quota_free_bytes() if remote else shutil.disk_usage(self.config.local_repository).free
                return {"status": "preview" if dry_run else "completed", "dry_run": dry_run, "max_unused": "5%", "max_repack_bytes": free - minimum_headroom_bytes, "completed_at": _now().isoformat() if not dry_run else None, "physical_bytes_before": before_bytes, "physical_bytes_after": after_bytes, "reclaimed_bytes": max(0, before_bytes - after_bytes) if not dry_run else 0, "free_bytes": observed_free, "physical_bytes_confirmed": True, "state": journal}
            except ResticError as exc:
                return {"status": "failed", "error": str(exc), "backup_verification_unchanged": True, "state": journal}
