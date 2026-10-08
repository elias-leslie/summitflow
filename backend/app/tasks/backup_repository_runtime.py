"""Integrate staged recovery payloads with independent encrypted repositories.

SQL is a catalogue, not the recovery dependency. Private, atomic checkpoints
survive a completed snapshot/copy whose SQL update was interrupted. Plaintext
staging has a stable path for Restic parents and is removed after each attempt.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import secrets
import shutil
import stat
import tarfile
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from ..logging_config import get_logger
from ..services.backup_keys import backup_key_directory
from ..storage import backups as backup_store
from ..storage.notifications import create_notification
from ..utils.shared_paths import get_host_config_root
from ..utils.transient_scratch import (
    ScratchError,
    ensure_scratch_capacity,
    restore_scratch,
    tree_bytes,
)
from ._retention_policy import HostRetentionPolicy
from .backup_activity import BackupCancelled, check_backup_cancelled, record_local_archive
from .backup_lock import BackupLockLeaseError, acquire_backup_lock, maintain_backup_lock
from .backup_native_archive import (
    _gzip_payload_file,
    _recoverable_file_filter,
    prepare_project_payload,
)
from .backup_native_infra import prepare_infrastructure_payload
from .backup_native_recovery import GIT_BUNDLE_NAME, RECOVERY_DIR_NAME, _is_sqlite_database
from .backup_restic import ResticAdapter, ResticConfig, ResticError
from .backup_utils import (
    REPOSITORY_CRITICAL_RESTORE_DAYS,
    build_storage_env,
    canonical_backup_source_roots,
)

_capture_batch: ContextVar[dict[str, dict[str, str]] | None] = ContextVar("repository_capture_batch", default=None)
_CRITICAL_SOURCE_IDS = {"infrastructure", "codex-config", "claude-config", "agent-skills", "claude-user-config"}
logger = get_logger(__name__)


def _repository_pair(config: ResticConfig) -> str:
    return hashlib.sha256((str(config.local_repository.resolve()) + "\n" + (config.remote_repository or "")).encode()).hexdigest()


@contextmanager
def _repository_maintenance_admission(config: ResticConfig) -> Iterator[None]:
    """Share capture admission with managed worker restart protection."""
    source_id = "__repository_maintenance__:" + _repository_pair(config)
    try:
        token = acquire_backup_lock(source_id)
    except Exception as exc:
        raise ResticError("Cannot verify repository maintenance admission; restore Redis access before retrying") from exc
    if token is None:
        raise ResticError("Repository maintenance admission blocked by active maintenance or a managed worker restart")
    try:
        with maintain_backup_lock(source_id, token):
            yield
    except BackupLockLeaseError as exc:
        raise ResticError("Repository maintenance admission ownership was lost; inspect active backups before retrying") from exc


@contextmanager
def repository_capture_batch() -> Iterator[dict[str, dict[str, str]]]:
    """Defer copy/check until every serial capture removed its plaintext tree."""
    batch: dict[str, dict[str, str]] = {}
    token = _capture_batch.set(batch)
    try:
        yield batch
    finally:
        _capture_batch.reset(token)


def _payload_fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash saved bytes and recovery state, never filesystem timestamp guesses."""
    root = Path(payload["snapshot_dir"])
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        check_backup_cancelled()
        metadata = path.lstat()
        digest.update(json.dumps([path.relative_to(root).as_posix(), stat.S_IFMT(metadata.st_mode), stat.S_IMODE(metadata.st_mode)]).encode())
        if path.is_symlink():
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    check_backup_cancelled()
                    digest.update(chunk)
    return digest.hexdigest()


def _unchanged_snapshot_available(adapter: ResticAdapter, previous: Mapping[str, Any]) -> bool:
    if adapter.repository_identity()["id"] != previous.get("repository_id"):
        raise ResticError("Unchanged capture checkpoint repository identity differs")
    return any(item["id"] == previous.get("snapshot_id") for item in adapter.snapshots())


def _payload_has_database(payload: Mapping[str, Any]) -> bool:
    if payload.get("expects_db") or payload.get("db_bytes"):
        return True
    # SQLite is already captured with the existing online backup API. Keep a
    # fresh point even when its consistent bytes equal the previous capture.
    return any(_is_sqlite_database(path) for path in Path(payload["snapshot_dir"]).rglob("*") if path.is_file() and not path.is_symlink())


def _capacity_admission(config: ResticConfig, state: Mapping[str, Any], source_id: str, *, staged_bytes: int = 0) -> dict[str, Any]:
    """Reserve existing host-policy headroom plus measured capture/growth peaks."""
    previous = state.get("sources", {}).get(source_id, {})
    history = previous.get("capacity", {})
    staging_peak = max(staged_bytes, int(history.get("staging_peak_bytes") or 0), int(previous.get("result", {}).get("logical_bytes") or 0))
    growth_peak = max(int(history.get("growth_peak_bytes") or 0), int(previous.get("result", {}).get("stored_bytes") or 0))
    policy = HostRetentionPolicy.from_env()
    filesystems: dict[int, dict[str, Any]] = {}
    for label, path, needed in (("staging", config.key_directory, max(0, staging_peak - staged_bytes)), ("repository", config.local_repository, max(staged_bytes, growth_peak))):
        while not path.exists():
            path = path.parent
        usage = shutil.disk_usage(path)
        reserve = int(policy.pressure_min_free_gb * 1024**3)
        entry = filesystems.setdefault(path.stat().st_dev, {"free_bytes": usage.free, "reserve_bytes": reserve, "required_bytes": 0, "paths": [], "under_pressure": 100 * usage.used / usage.total >= policy.pressure_disk_percent})
        entry["required_bytes"] += needed
        entry["paths"].append(label)
    admitted = all(item["free_bytes"] - item["required_bytes"] >= item["reserve_bytes"] for item in filesystems.values())
    return {"admitted": admitted, "staging_peak_bytes": staging_peak, "growth_peak_bytes": growth_peak, "filesystems": list(filesystems.values()), "reason": None if admitted else "insufficient-host-policy-headroom"}


def _copy_admission(adapter: ResticAdapter, state: Mapping[str, Any]) -> dict[str, Any]:
    """Budget copy from measured growth; first copy uses actual local objects."""
    journal = state.get("offsite", {})
    pending = set(journal.get("pending_snapshot_ids") or [])
    recorded = dict(journal.get("pending_stored_bytes") or {})
    for item in state["sources"].values():
        if item.get("snapshot_id") in pending and item.get("result", {}).get("stored_bytes") is not None:
            recorded[item["snapshot_id"]] = int(item["result"]["stored_bytes"])
    growth = sum(int(recorded[snapshot_id]) for snapshot_id in pending if snapshot_id in recorded)
    measured = int(journal.get("copy_growth_peak_bytes") or journal.get("new_object_bytes") or 0)
    required = max(measured, growth)
    if not journal.get("verified_at") or pending - recorded.keys() or not required:
        required = adapter.physical_bytes()
    free = adapter.quota_free_bytes()
    reserve = int(HostRetentionPolicy.from_env().pressure_min_free_gb * 1024**3)
    return {"admitted": free is not None and free - required >= reserve, "required_bytes": required, "free_bytes": free, "reserve_bytes": reserve, "evidence": "measured-copy-growth-and-pending-stored-bytes" if measured or growth else "local-physical-objects"}


def is_repository_backup(backup: Mapping[str, Any]) -> bool:
    return (backup.get("verification_json") or {}).get("format") == "restic-v1"


def _private_directory(path: Path) -> None:
    if not path.is_absolute() or path == Path(path.anchor):
        raise ResticError("A bounded absolute private directory is required")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ResticError("Private directory path must not contain symlinks")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    metadata = path.stat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise ResticError("Repository state directory must be private and owned by the service user")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise ResticError("Repository checkpoint is not a private regular file")
    with path.open() as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ResticError("Repository checkpoint is invalid")
    return value


def _save_json(path: Path, value: Mapping[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _checkpoint(config: ResticConfig) -> Iterator[tuple[Path, dict[str, Any]]]:
    config.validate()
    _approved_key_directory(config)
    root = config.key_directory / "restic-state"
    _private_directory(root)
    identity = _repository_pair(config)
    directory = root / identity
    _private_directory(directory)
    descriptor = os.open(directory / ".state.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        # A separate journal lock wraps adapter locks, including state reads.
        # It serializes capture, copy and maintenance for this repository pair.
        while True:
            check_backup_cancelled()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.1)
        state = _load_json(directory / "state.json")
        state.setdefault("version", 1)
        if state["version"] != 1:
            raise ResticError("Unsupported repository checkpoint")
        state.setdefault("sources", {})
        yield directory, state
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def initialize_repository(env: dict[str, str], *, local_only: bool = False) -> dict[str, Any]:
    """Create new private password files only when explicit initialization asks.

    References stay on the host; no key material is returned or logged. Existing
    credentials are never overwritten, and init never replaces a repository.
    Independent recovery-key escrow remains a separate qualification gate.
    """
    config = ResticConfig.from_env(env)
    _approved_key_directory(config)
    _private_directory(config.key_directory)
    paths = [config.local_password_file]
    if not local_only:
        if config.remote_password_file is None:
            raise ResticError("Remote password-file reference is required")
        paths.append(config.remote_password_file)
    for path in paths:
        if path.parent != config.key_directory or path.is_symlink():
            raise ResticError("Password files must be directly inside the private key directory")
        if not path.exists():
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(secrets.token_urlsafe(48) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
    adapter = ResticAdapter(config)
    readiness = adapter.readiness(local_only=local_only)
    if not readiness["ready"]:
        raise ResticError(str(readiness.get("error")))
    result = adapter.initialize(local_only=local_only)
    return {**result, "recovery_key_escrow_confirmed": False, "default_changed": False}


def _previous_bundle(adapter: ResticAdapter, previous: Mapping[str, Any], staging: Path) -> dict[str, Any] | None:
    git = (previous.get("recovery") or {}).get("git")
    snapshot_id = previous.get("snapshot_id")
    if not git or not snapshot_id:
        return None
    target = staging / "previous"
    target.mkdir(mode=0o700)
    try:
        restored = adapter.restore(str(snapshot_id), target, include=(f"{RECOVERY_DIR_NAME}/{GIT_BUNDLE_NAME}",))
        bundle = Path(restored["payload_root"]) / RECOVERY_DIR_NAME / GIT_BUNDLE_NAME
        return {"bundle_path": bundle, "git": git} if bundle.is_file() else None
    except (ResticError, OSError):
        # Missing/expired prior snapshots only disable this optimization. The
        # capture helper validates reuse and creates a full bundle otherwise.
        return None


def run_repository_backup(
    *, project_dir: str, source_id: str, env: dict[str, str], local_only: bool = False,
    infrastructure: bool = False,
) -> dict[str, Any]:
    config = ResticConfig.from_env(env)
    adapter = ResticAdapter(config)
    with _checkpoint(config) as (directory, state):
        admission = _capacity_admission(config, state, source_id)
        if not admission["admitted"]:
            raise ResticError("Capture blocked: insufficient host-policy headroom")
        payloads = directory / "payloads"
        _private_directory(payloads)
        staging = payloads / hashlib.sha256(source_id.encode()).hexdigest()
        # Only this task's private materialization is discarded, never a source
        # tree or encrypted snapshot. This also clears interrupted plaintext.
        if staging.exists():
            if staging.is_symlink():
                raise ResticError("Staging path must not be a symlink")
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        try:
            previous = state["sources"].get(source_id, {})
            # The Codex essentials profile intentionally omits native Git. Do
            # not download its previous multi-GB bundle merely to discard it.
            reuse = None if infrastructure or Path(project_dir).name == ".codex" else _previous_bundle(adapter, previous, staging)
            if infrastructure:
                payload = prepare_infrastructure_payload(Path(project_dir), staging, host_config_root=get_host_config_root())
            else:
                project_id = env.get("BACKUP_PROJECT_ID") or source_id
                payload = prepare_project_payload(
                    Path(project_dir), Path(project_dir).name, staging, {**env, "BACKUP_PROJECT_ID": project_id},
                    source_roots=canonical_backup_source_roots(), sensitive_paths=(config.key_directory,),
                    git_bundle_reuse=reuse,
                )
            payload["snapshot_dir"].chmod(0o700)
            fingerprint = _payload_fingerprint(payload)
            batch = _capture_batch.get()
            if batch is not None:
                batch[_repository_pair(config)] = env
            if not infrastructure and not _payload_has_database(payload) and previous.get("payload_fingerprint") == fingerprint and _unchanged_snapshot_available(adapter, previous):
                # Consistency validation and content hashing already ran. Only
                # an actual file-only payload may reuse its retained snapshot.
                result = copy.deepcopy(previous["result"])
                result.update(unchanged=True, data_added_bytes=0, stored_bytes=0)
                result["verification"].update(data_added_bytes=0, stored_bytes=0)
                result["verification"].update(unchanged=True, capture_checked_at=datetime.now(UTC).isoformat())
                previous["last_checked_at"] = result["verification"]["capture_checked_at"]
                _save_json(directory / "state.json", state)
                if local_only:
                    result["verification"]["offsite"] = {"status": "not_requested"}
                    result.update(status="completed")
                    result.pop("pending_path", None)
                elif batch is None:
                    synced = _sync(adapter, directory, state, str(result["snapshot_id"]), env)
                    result["verification"]["offsite"] = synced["verification"]["offsite"]
                    if synced["status"] == "verified":
                        result.update(status="completed")
                        result.pop("pending_path", None)
                        result["verification"].update(remote_snapshot_id=synced["remote_snapshot_id"], remote_repository_id=synced["remote_repository_id"])
                record_local_archive(result)
                return result
            admission = _capacity_admission(config, state, source_id, staged_bytes=int(payload.get("total_bytes") or 0))
            if not admission["admitted"]:
                raise ResticError("Capture blocked after staging: insufficient host-policy headroom")
            result = adapter.save_payload(source_id, payload, defer_check=True) if batch is not None else adapter.save_payload(source_id, payload)
            result["verification"].update(
                data_added_bytes=result.get("data_added_bytes"), stored_bytes=result.get("stored_bytes"),
                logical_bytes=result.get("logical_bytes"), total_files=payload["total_files"],
                has_db=bool(payload["db_bytes"]), verified_at=result["verification"].get("structural_check_at"),
            )
            result["verification"]["capture"]["db_dump_name"] = payload.get("db_dump_name", "pgdumpall.sql" if infrastructure else "database.sql")
            result["verification"]["storage_backend_id"] = env.get("BACKUP_STORAGE_BACKEND_ID")
            # Durable local completion precedes Drive and SQL. A failed remote
            # operation must not lose a usable local point.
            source_checkpoint = {
                "snapshot_id": result["snapshot_id"], "repository_id": result["repository_id"],
                "baseline_snapshot_id": previous.get("baseline_snapshot_id", result["snapshot_id"]),
                "last_good_snapshot_id": previous.get("last_good_snapshot_id", result["snapshot_id"]),
                "recovery": payload.get("recovery", {}), "result": result,
                "payload_fingerprint": fingerprint,
                "capacity": {"staging_peak_bytes": admission["staging_peak_bytes"], "growth_peak_bytes": max(admission["growth_peak_bytes"], int(result.get("stored_bytes") or 0))},
                "completed_at": datetime.now(UTC).isoformat(),
            }
            state["sources"][source_id] = source_checkpoint
            if not local_only:
                journal = state.setdefault("offsite", {})
                pending = journal.setdefault("pending_snapshot_ids", [])
                if result["snapshot_id"] not in pending:
                    pending.append(result["snapshot_id"])
                if result.get("stored_bytes") is not None:
                    journal.setdefault("pending_stored_bytes", {})[result["snapshot_id"]] = int(result["stored_bytes"])
            _save_json(directory / "state.json", state)
            record_local_archive(result)
            if local_only:
                result["verification"]["offsite"] = {"status": "not_requested"}
            elif batch is not None:
                result["verification"]["offsite"] = {"status": "pending", "reason": "repository-batch-copy"}
                result.update(status="completed_pending_upload", pending_path=result["location"])
            else:
                synced: dict[str, Any]
                try:
                    synced = _sync(adapter, directory, state, result["snapshot_id"], env)
                except (ResticError, OSError) as exc:
                    synced = {"status": "pending", "verification": {"offsite": {"status": "pending", "error": str(exc)}}}
                result["verification"]["offsite"] = synced["verification"]["offsite"]
                if synced["status"] == "verified":
                    result["verification"].update(
                        remote_repository_id=synced["remote_repository_id"],
                        remote_snapshot_id=synced["remote_snapshot_id"],
                    )
                    source_checkpoint["last_good_snapshot_id"] = result["snapshot_id"]
                else:
                    result.update(status="completed_pending_upload", pending_path=result["location"])
            source_checkpoint["result"] = result
            _save_json(directory / "state.json", state)
            return result
        finally:
            shutil.rmtree(staging)


def _sync(adapter: ResticAdapter, directory: Path, state: dict[str, Any], snapshot_id: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    def persist(journal: dict[str, Any]) -> None:
        state["offsite"] = journal
        _save_json(directory / "state.json", state)

    admission = _copy_admission(adapter, state)
    if not admission["admitted"]:
        return {"status": "pending", "capacity": admission, "verification": {"offsite": {"status": "pending", "reason": "insufficient-copy-headroom", "capacity": admission}}}
    result = adapter.sync(snapshot_id, state=state.get("offsite"), persist=persist)
    if result.get("status") == "verified":
        journal = state["offsite"]
        journal["copy_growth_peak_bytes"] = max(int(journal.get("copy_growth_peak_bytes") or 0), int(journal.get("new_object_bytes") or 0))
        journal["pending_stored_bytes"] = {key: value for key, value in (journal.get("pending_stored_bytes") or {}).items() if key in journal.get("pending_snapshot_ids", [])}
        _reconcile_offsite(state, result, env)
        _save_json(directory / "state.json", state)
    return result


def _repository_rows(env: Mapping[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page, total = backup_store.list_backups(limit=100, offset=offset)
        rows.extend(row for row in page if is_repository_backup(row) and row.get("storage_backend_id") == env.get("BACKUP_STORAGE_BACKEND_ID") and row.get("status") in {"completed", "completed_pending_upload"})
        offset += len(page)
        if not page or offset >= total:
            return rows


def _reconcile_offsite(state: dict[str, Any], result: Mapping[str, Any], env: Mapping[str, str] | None) -> None:
    journal = state.get("offsite", {})
    mapping = journal.get("remote_snapshots", {})
    offsite = result["verification"]["offsite"]
    for previous in state["sources"].values():
        snapshot_id = previous.get("snapshot_id")
        if snapshot_id in mapping:
            saved = previous["result"]
            saved["verification"].update(offsite=offsite, remote_snapshot_id=mapping[snapshot_id], remote_repository_id=journal["remote_repository_id"])
            saved.update(status="completed")
            saved.pop("pending_path", None)
            previous["last_good_snapshot_id"] = snapshot_id
    if env is None:
        return
    for row in _repository_rows(env):
        verification = row.get("verification_json") or {}
        snapshot_id = verification.get("snapshot_id")
        if snapshot_id in mapping and verification.get("repository_id") == journal.get("local_repository_id"):
            backup_store.merge_backup_verification_json(str(row["id"]), {"offsite": offsite, "remote_snapshot_id": mapping[snapshot_id], "remote_repository_id": journal["remote_repository_id"]})
            if row.get("status") == "completed_pending_upload":
                backup_store.update_backup_status(str(row["id"]), "completed")


def sync_repository_batch(batch: Mapping[str, dict[str, str]]) -> dict[str, Any]:
    """One structural check/copy per pair; include persisted failed-copy backlog."""
    from .backup_restic_pilot import pilot_reserves_backend
    from .backup_utils import storage_config_env

    pairs = dict(batch)
    for backend in backup_store.list_backends(enabled_only=True):
        config = backend.get("config") or {}
        if config.get("engine") != "restic" or config.get("restic_automatic_maintenance") is False or pilot_reserves_backend(str(backend["id"])):
            continue
        env = storage_config_env({**config, "__backend_type": backend["backend_type"], "__backend_id": backend["id"]})
        pairs.setdefault(_repository_pair(ResticConfig.from_env(env)), env)
    results: dict[str, Any] = {}
    for identity, env in pairs.items():
        try:
            config = ResticConfig.from_env(env)
            adapter = ResticAdapter(config)
            with _repository_maintenance_admission(config), _checkpoint(config) as (directory, state):
                journal = state.setdefault("offsite", {})
                pending = journal.setdefault("pending_snapshot_ids", [])
                local_id = adapter.repository_identity()["id"]
                for row in _repository_rows(env):
                    verification = row.get("verification_json") or {}
                    snapshot_id = verification.get("snapshot_id")
                    if verification.get("repository_id") == local_id and snapshot_id and verification.get("offsite", {}).get("status") not in {"verified", "not_requested"} and snapshot_id not in pending:
                        pending.append(snapshot_id)
                    if snapshot_id in pending and verification.get("stored_bytes") is not None:
                        journal.setdefault("pending_stored_bytes", {})[snapshot_id] = int(verification["stored_bytes"])
                for source in state["sources"].values():
                    saved = source.get("result", {}).get("verification", {})
                    if saved.get("offsite", {}).get("status") not in {"verified", "not_requested"} and source["snapshot_id"] not in pending:
                        pending.append(source["snapshot_id"])
                unchecked = [item for item in state["sources"].values() if item.get("result", {}).get("verification", {}).get("structural_check_pending")]
                _save_json(directory / "state.json", state)
                if unchecked:
                    check = adapter.check()
                    check.setdefault("method", "restic-structural-check")
                    if not check.get("verified"):
                        previous = state.setdefault("maintenance", {}).setdefault("local", {})
                        previous["monthly_result"] = {key: value for key, value in check.items() if key != "state"}
                        previous.pop("monthly_checked_at", None)
                        _notify_repository_result(state, env, "local-integrity", check)
                        _save_json(directory / "state.json", state)
                        raise ResticError("Repository batch structural check failed")
                    _notify_repository_result(state, env, "local-integrity", check)
                    for item in unchecked:
                        item["result"]["verification"].update(structural_check_pending=False, structural_check_at=check["checked_at"])
                    for row in _repository_rows(env):
                        if (row.get("verification_json") or {}).get("repository_id") == local_id and (row.get("verification_json") or {}).get("structural_check_pending"):
                            backup_store.merge_backup_verification_json(str(row["id"]), {"structural_check_pending": False, "structural_check_at": check["checked_at"]})
                    _save_json(directory / "state.json", state)
                if pending and config.remote_repository:
                    results[identity] = _sync(adapter, directory, state, pending[-1], env)
                else:
                    results[identity] = {"status": "skipped", "reason": "no-pending-offsite-snapshots"}
        except BackupCancelled:
            raise
        except Exception as exc:
            results[identity] = {"status": "pending", "error": str(exc)}
    return results


def _backup_environment(backup: Mapping[str, Any]) -> dict[str, str]:
    source_id = str(backup.get("source_id") or backup.get("project_id") or "")
    verification = backup.get("verification_json") or {}
    backend_id = backup.get("storage_backend_id") or verification.get("storage_backend_id")
    if not backend_id:
        raise ResticError("Repository backup has no recorded storage backend; default fallback refused")
    env = build_storage_env(source_id, str(backend_id))
    if env.get("BACKUP_ENGINE") != "restic":
        raise ResticError("Recorded backend is no longer a repository backend")
    return env


def _approved_key_directory(config: ResticConfig) -> None:
    if not config.key_directory.resolve().is_relative_to(backup_key_directory().resolve()):
        raise ResticError("Restic credentials and staging must remain under the globally excluded backup key directory")


def _assert_repository_identity(adapter: ResticAdapter, verification: Mapping[str, Any], *, remote: bool = False) -> None:
    expected = verification.get("remote_repository_id" if remote else "repository_id")
    if not expected or adapter.repository_identity(remote=remote)["id"] != expected:
        raise ResticError("Recorded repository identity does not match the live configured repository")


def sync_repository_backup(backup: Mapping[str, Any]) -> dict[str, Any]:
    verification = backup.get("verification_json") or {}
    config = ResticConfig.from_env(_backup_environment(backup))
    adapter = ResticAdapter(config)
    snapshot_id = str(verification.get("snapshot_id") or "")
    _assert_repository_identity(adapter, verification)
    with _checkpoint(config) as (directory, state):
        # Also guard SQL pointing at a repurposed backend using live config.
        if not any(item.get("repository_id") == verification.get("repository_id") for item in state["sources"].values()):
            raise ResticError("Recorded snapshot repository is not the configured repository")
        return _sync(adapter, directory, state, snapshot_id, _backup_environment(backup))


@contextmanager
def materialize_repository_archive(backup: Mapping[str, Any], *, remote: bool = False) -> Iterator[Path]:
    """Bridge verified repository restores to the existing safe restore/drill.

    Only disposable recovery staging is tarred; stored backups remain plain
    chunkable trees. This preserves established SQL/config restore contracts.
    """
    verification = backup.get("verification_json") or {}
    config = ResticConfig.from_env(_backup_environment(backup))
    adapter = ResticAdapter(config)
    _approved_key_directory(config)
    _assert_repository_identity(adapter, verification, remote=remote)
    snapshot_id = verification.get("remote_snapshot_id") if remote else verification.get("snapshot_id")
    if not snapshot_id:
        raise ResticError("A verified snapshot reference is required")
    # The restored tree and its tar/gzip copy coexist. Known payload bytes are
    # admission evidence; remeasure before each additional staging copy.
    with restore_scratch("st-repository-restore-", required_bytes=2 * _known_restore_bytes(backup)) as scratch_path:
        target = scratch_path / "materialized"
        target.mkdir(mode=0o700)
        restored = adapter.restore(str(snapshot_id), target, remote=remote)
        payload_root = Path(restored["payload_root"])
        ensure_scratch_capacity(scratch_path, tree_bytes(payload_root))
        infrastructure = str(backup.get("source_id")) == "infrastructure"
        plain_name = "pgdumpall.sql" if infrastructure else "database.sql"
        capture = verification.get("capture", {})
        dump_name = capture.get("db_dump_name", plain_name)
        if not isinstance(dump_name, str) or Path(dump_name).is_absolute() or ".." in Path(dump_name).parts:
            raise ResticError("Captured SQL dump path is invalid")
        dump = payload_root / dump_name
        if dump.is_file():
            _gzip_payload_file(dump, payload_root / f"{plain_name}.gz")
            dump.unlink()
        ensure_scratch_capacity(scratch_path, tree_bytes(payload_root))
        archive = scratch_path / "recovery.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(payload_root, arcname="infrastructure" if infrastructure else "payload", filter=_recovery_archive_filter)
        archive.chmod(0o600)
        ensure_scratch_capacity(scratch_path, 0)
        yield archive


def _known_restore_bytes(backup: Mapping[str, Any]) -> int:
    verification = backup.get("verification_json") or {}
    return max(0, int(verification.get("logical_bytes") or 0),
               int(backup.get("total_bytes") or backup.get("size_bytes") or 0))


def _recovery_archive_filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    # Keep directories so tarfile recurses; actual extraction subsequently
    # applies the existing member/path/link validation before any write.
    return member if member.isdir() else _recoverable_file_filter(member)


def repository_status(env: dict[str, str]) -> dict[str, Any]:
    config = ResticConfig.from_env(env)
    adapter = ResticAdapter(config)
    readiness = adapter.readiness(local_only=not bool(config.remote_repository))
    if not readiness["ready"]:
        return readiness
    with _checkpoint(config) as (_, state):
        return {
            **readiness, "sources": {key: {field: value.get(field) for field in ("snapshot_id", "completed_at", "last_good_snapshot_id")} for key, value in state["sources"].items()},
            "offsite": {key: state.get("offsite", {}).get(key) for key in ("status", "verified_at", "pending_snapshot_ids", "pending_objects", "mismatches", "new_object_bytes")},
            "maintenance": state.get("maintenance", {}),
            "prune_qualified": config.offsite_prune_qualified,
            "cutover_qualified": False,
            "cutover_status": "requires-owner-approved-recovery-coverage-and-measured-qualification",
            "local_repository_physical_bytes": sum(path.stat().st_size for path in config.local_repository.rglob("*") if path.is_file() and not path.is_symlink()),
            "new_object_bytes_are_network_traffic": False,
        }


def _critical_restore_reason(result: Mapping[str, Any]) -> str | None:
    if result.get("status") != "failed":
        return None
    failed = (result.get("sources") or {}).get(result.get("failed_source"), {})
    if failed.get("mapped_links_pending"):
        return "mapped-links-unresolved"
    if "failed to lock repository" in str(result.get("error") or ""):
        return "repository-locked"
    return "restore-failed"


def _notify_repository_result(state: dict[str, Any], env: Mapping[str, str], operation: str, result: Mapping[str, Any]) -> None:
    """Alert on meaningful failed/recovered transitions, not routine attempts."""
    failed = result.get("status") == "failed" or result.get("verified") is False
    verified = result.get("status") == "verified" or result.get("verified") is True
    if not failed and not verified:
        return
    journal = state.setdefault("repository_notifications", {})
    previous = journal.get(operation) or {}
    method = result.get("method")
    if failed and previous.get("active") is True and (
        previous.get("method") == "restic-monthly-bucket" or method == "restic-monthly-bucket"
    ):
        # Payload failure is stronger evidence than structural failure. Keep
        # its scope until payload verification passes, even across deduped or
        # differently worded structural failures.
        method = "restic-monthly-bucket"
        previous["method"] = method
    source_id = result.get("failed_source") if result.get("failed_source") in _CRITICAL_SOURCE_IDS else None
    if operation == "critical-restore":
        reason = _critical_restore_reason(result)
        source = (result.get("sources") or {}).get(source_id, {})
        details = source.get("mapped_links_pending") or []
        title = "Weekly backup restore failed" if failed else "Weekly backup restore recovered"
        if reason == "mapped-links-unresolved":
            message = "A required configuration link could not be restored. Backup retention remains blocked. Review backup readiness for the affected source."
        elif reason == "repository-locked":
            message = "The repository was locked when the offsite restore ran. Backup retention remains blocked. Review active backup work before retrying."
        else:
            message = "The combined offsite restore did not pass. Backup retention remains blocked. Review backup readiness for the failed source."
        recovered = "All required sources passed the combined offsite restore. Backup readiness shows the test date and results."
    else:
        reason = "repository-locked" if "failed to lock repository" in str(result.get("error") or "") else "integrity-check-failed"
        details = []
        label = "Local" if operation == "local-integrity" else "Offsite"
        title = f"{label} backup integrity check {'failed' if failed else 'recovered'}"
        message = f"The {label.lower()} repository integrity check did not pass. Backup retention remains blocked. Review backup readiness before retrying."
        recovered = f"The {label.lower()} repository integrity check passed after its earlier failure."
    fingerprint = hashlib.sha256(json.dumps([reason, source_id, details], sort_keys=True).encode()).hexdigest()
    if failed and previous.get("active") is True and previous.get("fingerprint") == fingerprint:
        return
    if verified and previous.get("active") is not True:
        return
    if verified and previous.get("method") == "restic-monthly-bucket" and result.get("method") != "restic-monthly-bucket":
        return  # A structural check does not clear a failed payload readback.
    backend_id = str(env.get("BACKUP_STORAGE_BACKEND_ID") or "")
    event = "failed" if failed else "recovered"
    try:
        create_notification(
            project_id="summitflow", notification_type="system", title=title,
            message=message if failed else recovered, severity="error" if failed else "info",
            metadata={"backup_event": event, "backend_id": backend_id, "operation": operation,
                      "failed_source_id": source_id, "reason": reason if failed else None},
            dedupe_key=f"backup:{backend_id}:{operation}:{event}:{fingerprint}",
        )
    except Exception:
        logger.warning("repository_backup_notification_failed", backend_id=backend_id, operation=operation)
        return
    journal[operation] = {"active": failed, "fingerprint": fingerprint, "method": method}


def repository_recovery_status(env: dict[str, str]) -> dict[str, Any]:
    """Observe atomically replaced recovery evidence without locks or Restic."""
    def timestamp(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Invalid recovery timestamp")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Recovery timestamp needs a timezone")
        return parsed.astimezone(UTC).isoformat()

    empty: dict[str, Any] = {
        "status": "untested", "last_success_at": None, "latest_attempt": None,
        "required_source_ids": [], "verified_source_ids": [], "missing_source_ids": [],
    }
    try:
        config = ResticConfig.from_env(env)
        _approved_key_directory(config)
        path = config.key_directory / "restic-state" / _repository_pair(config) / "state.json"
        if any(component.is_symlink() for component in (path, *path.parents)):
            raise ResticError("Recovery observation must not follow symlinks")
        state = _load_json(path)
        maintenance = state.get("maintenance") or {}
        result = maintenance.get("critical_restore_result") or {}
        success = maintenance.get("critical_restore_success") or (result if result.get("status") == "verified" else {})
        attempt = maintenance.get("critical_restore_attempt") or (
            result if result.get("status") in {"verified", "failed"} else {}
        )
        failure = maintenance.get("critical_restore_failure") or (result if result.get("status") == "failed" else {})
        last_success = timestamp(success.get("verified_at") or maintenance.get("critical_restore_at"))
        status = "untested"
        if failure:
            status = "failed"
        elif attempt.get("status") == "running":
            status = "running"
        elif result.get("status") == "pending":
            status = "pending"
        elif last_success:
            verified_at = datetime.fromisoformat(last_success.replace("Z", "+00:00"))
            status = "verified" if verified_at > datetime.now(UTC) - timedelta(days=REPOSITORY_CRITICAL_RESTORE_DAYS) else "stale"
        latest = None
        if attempt:
            if attempt.get("status") not in {"verified", "failed", "running"}:
                raise ValueError("Unknown recovery attempt status")
            latest = {
                "status": attempt.get("status"), "attempted_at": timestamp(attempt.get("attempted_at")),
                "completed_at": timestamp(attempt.get("completed_at") or attempt.get("verified_at")),
                "failed_source_id": attempt.get("failed_source") if attempt.get("failed_source") in _CRITICAL_SOURCE_IDS else None,
                "reason": _critical_restore_reason(attempt),
                "cached": bool(result.get("cached")),
            }
        required = result.get("required_source_ids") or attempt.get("required_source_ids") or list((success.get("selected_backups") or {}).keys())
        verified = [key for key, value in (success.get("sources") or {}).items() if value.get("ok") is True]
        return {
            "status": status, "last_success_at": last_success, "latest_attempt": latest,
            "required_source_ids": sorted(set(required) & _CRITICAL_SOURCE_IDS),
            "verified_source_ids": sorted(set(verified) & _CRITICAL_SOURCE_IDS),
            "missing_source_ids": sorted(set(result.get("missing_sources") or []) & _CRITICAL_SOURCE_IDS),
        }
    except (ResticError, OSError, ValueError, TypeError, AttributeError):
        return {**empty, "status": "unavailable"}


def maintain_repository(env: dict[str, str], *, dry_run: bool = True, force_critical_restore: bool = False) -> dict[str, Any]:
    """Monthly rotating readback, guarded daily expiry and weekly prune.

    Both destructive retention paths stay preview-only before cold recovery is
    qualified. Only forgotten snapshot catalogue rows are reconciled afterwards.
    """
    config = ResticConfig.from_env(env)
    adapter = ResticAdapter(config)
    with _repository_maintenance_admission(config), _checkpoint(config) as (directory, state):
        maintenance = state.setdefault("maintenance", {})
        now = datetime.now(UTC)
        preview = dry_run or not config.offsite_prune_qualified
        sources = backup_store.list_sources()
        windows = {str(source["id"]): int(source.get("retention_days") or 14) for source in sources if source.get("enabled")}
        offsite = state.get("offsite", {})
        pending = list(offsite.get("pending_snapshot_ids") or [])
        pending.extend(value["snapshot_id"] for value in state["sources"].values() if (value.get("result", {}).get("verification", {}).get("offsite", {}).get("status") not in {"verified", "not_requested"}))
        last_good = {key: value.get("last_good_snapshot_id", value["snapshot_id"]) for key, value in state["sources"].items()}
        pins = list(state.get("pinned_snapshot_ids") or [])
        if not config.offsite_prune_qualified:
            pins.extend(value["baseline_snapshot_id"] for value in state["sources"].values())
        results: dict[str, Any] = {"dry_run": preview}
        if config.remote_repository:
            results["critical_restore"] = _weekly_critical_restore(
                env, maintenance, force=force_critical_restore,
                persist=lambda: _save_json(directory / "state.json", state),
            )
            maintenance["critical_restore_result"] = results["critical_restore"]
            _notify_repository_result(state, env, "critical-restore", results["critical_restore"])
            # A later repository check may raise; keep the expensive drill's
            # result durable independently so that restart retries reuse it.
            _save_json(directory / "state.json", state)

        def persist(journal: dict[str, Any]) -> None:
            state["offsite"] = journal
            _save_json(directory / "state.json", state)

        repositories = [False, True] if config.remote_repository else [False]
        for remote in repositories:
            label = "remote" if remote else "local"
            previous = maintenance.setdefault(label, {})
            checked_at = previous.get("monthly_checked_at")
            if not checked_at or datetime.fromisoformat(checked_at) < now - timedelta(days=1):
                check = adapter.check(remote=remote, monthly_state=previous.get("monthly", {}))
                check.setdefault("method", "restic-monthly-bucket")
                previous["monthly"] = check["state"]
                if check["verified"]:
                    previous["monthly_checked_at"] = check["checked_at"]
                previous["monthly_result"] = {key: value for key, value in check.items() if key != "state"}
                _notify_repository_result(state, env, f"{label}-integrity", check)
                _save_json(directory / "state.json", state)
        pair_healthy = all((maintenance["remote" if remote else "local"].get("monthly_result") or {}).get("verified") is True for remote in repositories)
        critical_status = results.get("critical_restore", {}).get("status")
        if critical_status == "failed" or (not preview and config.remote_repository and critical_status not in {"verified", "skipped"}):
            pair_healthy = False
        if pair_healthy and not preview and (offsite.get("maintenance") or {}).get("status") == "pending" and offsite["maintenance"].get("operation") == "prune":
            resumed = adapter.prune(remote=True, state=offsite, persist=persist, available_bytes=adapter.quota_free_bytes(), dry_run=False)
            offsite = state.get("offsite", {})
            results["resumed_prune"] = resumed
            if resumed.get("status") == "failed" or (offsite.get("maintenance") or {}).get("status") == "pending":
                pair_healthy = False
            elif resumed.get("status") == "completed":
                maintenance["remote"]["pruned_at"] = resumed["completed_at"]
        for remote in repositories:
            label = "remote" if remote else "local"
            previous = maintenance[label]
            if not pair_healthy:
                results[label] = {"monthly": previous.get("monthly_result"), "retention": {"status": "skipped", "reason": "integrity-check-failed"}, "prune": {"status": "skipped", "reason": "integrity-check-failed"}}
                continue
            mapping = offsite.get("remote_snapshots", {}) if remote else {}
            def remap(value: str, mapping: dict[str, str] = mapping) -> str:
                return mapping.get(value, value)
            selection = adapter.retention(windows, remote=remote, pinned=[remap(value) for value in pins], pending=[remap(value) for value in pending], last_good={key: remap(value) for key, value in last_good.items()}, state=offsite, persist=persist, dry_run=preview)
            offsite = state.get("offsite", {})
            free = shutil.disk_usage(config.local_repository).free if not remote else None
            # Provider quota must be freshly supplied before actual Drive prune;
            # no guessed capacity or unbounded repack allowance.
            if remote:
                free = adapter.quota_free_bytes()
            prune = adapter.prune(remote=remote, state=offsite, persist=persist, last_prune_at=previous.get("pruned_at"), available_bytes=free, dry_run=preview)
            offsite = state.get("offsite", {})
            if prune.get("status") == "completed":
                previous["pruned_at"] = prune["completed_at"]
            results[label] = {"monthly": previous.get("monthly_result"), "retention": selection, "prune": prune}
        if not preview and pair_healthy:
            results["catalogue_rows_deleted"] = _reconcile_catalogue(adapter, env)
        results["status"] = "failed" if not pair_healthy or repository_maintenance_failed(results) else "completed"
        results["summary"] = {"result": results["status"], "reclaimed_bytes": sum(int(results.get(label, {}).get("prune", {}).get("reclaimed_bytes") or 0) for label in ("local", "remote")), "free_bytes": {label: results.get(label, {}).get("prune", {}).get("free_bytes") for label in ("local", "remote")}, "blockers": [label for label in ("local", "remote") if results.get(label, {}).get("prune", {}).get("reason")], "evidence": str(directory / "state.json")}
        maintenance["last_run_at"] = now.isoformat()
        maintenance["result"] = results
        _save_json(directory / "state.json", state)
        return results


def _critical_restore_implementation_fingerprint() -> str:
    """Invalidate failed drill reuse when its deployed recovery code changes."""
    from .backup_restore_drill import DRILL_SCRIPT

    digest = hashlib.sha256()
    for path in (
        Path(__file__),
        *(Path(__file__).with_name(name) for name in (
            "backup_executor.py", "backup_native_recovery.py", "backup_native_restore.py",
            "backup_native_archive.py", "backup_restic.py", "backup_restore_drill.py",
            "backup_activity.py",
        )),
        Path(__file__).parents[1] / "utils" / "transient_scratch.py",
        DRILL_SCRIPT,
    ):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _weekly_critical_restore(env: dict[str, str], maintenance: dict[str, Any], *, force: bool = False, persist: Callable[[], None] | None = None) -> dict[str, Any]:
    """Restore essential configuration and databases weekly from offsite only."""
    previous = maintenance.get("critical_restore_at")
    last_result = maintenance.get("critical_restore_result") or {}
    if last_result.get("status") == "verified":
        # Upgrade the pre-journal-format success before a cadence skip or new
        # attempt replaces its only detailed copy. Observation stays read-only.
        hydrated = False
        for field in ("critical_restore_success", "critical_restore_attempt"):
            if not maintenance.get(field):
                maintenance[field] = copy.deepcopy(last_result)
                hydrated = True
        if hydrated and persist:
            persist()
    if last_result.get("status") == "failed":
        maintenance["critical_restore_failure"] = last_result
    last_failure = maintenance.get("critical_restore_failure") or {}
    cadence_verified = last_result.get("status") == "verified" or (
        last_result.get("status") == "skipped" and last_result.get("reason") == "weekly-cadence"
    )
    if not force and not last_failure and cadence_verified and previous and datetime.fromisoformat(previous) > datetime.now(UTC) - timedelta(days=REPOSITORY_CRITICAL_RESTORE_DAYS):
        return {"status": "skipped", "reason": "weekly-cadence", "verified_at": previous}
    # Conversation trees remain fully backed up and covered by provider hashes
    # and rotating payload checks. Re-downloading them in full every week adds
    # transfer/staging cost without exercising the critical configuration or
    # database rebuilds this drill is intended to verify.
    critical = _CRITICAL_SOURCE_IDS
    enabled = {str(source["id"]) for source in backup_store.list_sources() if source.get("enabled")}
    required = critical & enabled
    selected: dict[str, dict[str, Any]] = {}
    for source_id in sorted(required):
        rows, _ = backup_store.list_backups(source_id=source_id, limit=100)
        selected_row = next((row for row in rows if is_repository_backup(row) and row.get("storage_backend_id") == env.get("BACKUP_STORAGE_BACKEND_ID") and (row.get("verification_json", {}).get("offsite", {}).get("status") == "verified")), None)
        if selected_row is not None:
            selected[source_id] = selected_row
    missing = sorted(required - selected.keys())
    if missing or not selected:
        pending_result = {"status": "pending", "reason": "critical-offsite-coverage-missing", "missing_sources": missing, "required_source_ids": sorted(required)}
        maintenance["critical_restore_result"] = pending_result
        return pending_result
    from .backup_executor import _complete_mapped_recovery
    from .backup_native_restore import restore_isolated_archive
    from .backup_restore_drill import _record_drill_result, _run_drill_script

    selected_points = {
        source_id: {
            "backup_id": backup["id"],
            **{field: backup["verification_json"].get(field) for field in (
                "snapshot_id", "remote_snapshot_id", "repository_id", "remote_repository_id",
            )},
        }
        for source_id, backup in selected.items()
    }
    fingerprint = hashlib.sha256(json.dumps({
        # Catalogue rows may be renewed for an unchanged captured snapshot.
        # Keep their IDs in attempt evidence, not in recovery input identity.
        "selected_snapshots": {
            source_id: {field: value for field, value in point.items() if field != "backup_id"}
            for source_id, point in selected_points.items()
        },
        "backend_id": env.get("BACKUP_STORAGE_BACKEND_ID"),
        "repository_pair": [env.get("RESTIC_LOCAL_REPOSITORY"), env.get("RESTIC_REMOTE_REPOSITORY")],
        "implementation": _critical_restore_implementation_fingerprint(),
    }, sort_keys=True).encode()).hexdigest()
    if not force and last_failure.get("status") == "failed" and last_failure.get("input_fingerprint") == fingerprint:
        return {**copy.deepcopy(last_failure), "cached": True, "reason": "unchanged-failed-recovery-inputs"}

    attempted_at = datetime.now(UTC).isoformat()
    maintenance["critical_restore_attempt"] = {
        "status": "running", "attempted_at": attempted_at, "selected_backups": selected_points,
        "input_fingerprint": fingerprint, "required_source_ids": sorted(required),
    }
    if persist:
        persist()

    def finish(result: dict[str, Any]) -> dict[str, Any]:
        result.update(input_fingerprint=fingerprint, selected_backups=selected_points, attempted_at=attempted_at, completed_at=datetime.now(UTC).isoformat(), required_source_ids=sorted(required))
        maintenance["critical_restore_result"] = result
        maintenance["critical_restore_attempt"] = copy.deepcopy(result)
        if result["status"] == "failed":
            maintenance["critical_restore_failure"] = result
        elif result["status"] == "verified":
            maintenance.pop("critical_restore_failure", None)
            maintenance["critical_restore_success"] = copy.deepcopy(result)
        if persist:
            persist()
        return result

    evidence: dict[str, Any] = {}
    retained_config_bytes = sum(_known_restore_bytes(backup) for source_id, backup in selected.items()
                                if source_id != "infrastructure")
    # Persistent mapped trees coexist with one serial restore's payload,
    # archive and extraction. Arbitrary database expansion remains unknown.
    peak_copy_bytes = max(3 * _known_restore_bytes(backup) for backup in selected.values())
    with ExitStack() as staging:
        try:
            isolated = staging.enter_context(restore_scratch(
                "st-critical-offsite-drill-", required_bytes=retained_config_bytes + peak_copy_bytes,
            ))
        except (ScratchError, OSError) as exc:
            return finish({"status": "failed", "sources": evidence, "error": str(exc)})
        targets: dict[str, Path] = {}

        def restore_source(source_id: str, backup: dict[str, Any]) -> dict[str, Any] | None:
            drill_result: dict[str, Any] | None = None
            try:
                with materialize_repository_archive(backup, remote=True) as archive:
                    if source_id == "infrastructure":
                        drill_result = _run_drill_script(str(archive), str(backup["id"]))
                        _record_drill_result(source_id, str(backup["id"]), ok=drill_result.get("ok") is True, result=drill_result)
                        if drill_result.get("ok") is not True:
                            raise ResticError("Infrastructure database/Redis/config restore drill failed")
                    else:
                        target = isolated / source_id
                        ensure_scratch_capacity(isolated, _known_restore_bytes(backup))
                        restore_isolated_archive(archive, target)
                        ensure_scratch_capacity(isolated, 0)
                        targets[source_id] = target
                evidence[source_id] = {"ok": True, "backup_id": backup["id"], "remote_snapshot_id": backup["verification_json"]["remote_snapshot_id"]}
            except BackupCancelled:
                raise
            except Exception as exc:
                if source_id == "infrastructure" and drill_result is None:
                    _record_drill_result(source_id, str(backup["id"]), ok=False, error=str(exc))
                evidence[source_id] = {**selected_points[source_id], "ok": False, "error": str(exc)}
                return finish({"status": "failed", "sources": evidence, "failed_source": source_id, "error": str(exc)})
            return None

        # Validate the combined configuration first: unresolved cross-source
        # links must fail before downloading or loading the database archive.
        for source_id, backup in selected.items():
            if source_id != "infrastructure":
                failure = restore_source(source_id, backup)
                if failure is not None:
                    return failure
        for source_id, target in targets.items():
            try:
                mapped = _complete_mapped_recovery(target, {key: root for key, root in targets.items() if key in {"codex-config", "claude-config", "agent-skills"}})
                evidence[source_id].update(mapped)
                if not mapped["recovery_complete"]:
                    raise ResticError("Canonical configuration links remain unresolved")
            except BackupCancelled:
                raise
            except Exception as exc:
                evidence[source_id].update(ok=False, error=str(exc))
                return finish({"status": "failed", "sources": evidence, "failed_source": source_id, "error": str(exc)})
        if "infrastructure" in selected:
            failure = restore_source("infrastructure", selected["infrastructure"])
            if failure is not None:
                return failure
    maintenance["critical_restore_at"] = datetime.now(UTC).isoformat()
    return finish({"status": "verified", "verified_at": maintenance["critical_restore_at"], "sources": evidence, "remote_only": True})


def repository_maintenance_failed(value: object) -> bool:
    """Retain truth across nested check, restore, retention and prune results."""
    if not isinstance(value, Mapping):
        return False
    evidence = cast("Mapping[str, Any]", value)
    if evidence.get("status") in {"failed", "error", "pending"} or evidence.get("verified") is False:
        return True
    return any(repository_maintenance_failed(child) for child in evidence.values())


def run_repository_maintenance() -> dict[str, Any]:
    """Use the existing scheduler, not a new daemon or per-project schedule."""
    from .backup_restic_pilot import pilot_reserves_backend
    from .backup_utils import storage_config_env

    results: dict[str, Any] = {}
    for backend in backup_store.list_backends(enabled_only=True):
        config = backend.get("config") or {}
        if config.get("engine") != "restic":
            continue
        if config.get("restic_automatic_maintenance") is False:
            continue  # Retired pilot points remain readable without recurring scans.
        if pilot_reserves_backend(str(backend["id"])):
            continue  # Daily runner owns *all* pilot maintenance in its measured window.
        try:
            env = storage_config_env({**config, "__backend_type": backend["backend_type"], "__backend_id": backend["id"]})
            results[str(backend["id"])] = maintain_repository(env, dry_run=env.get("RESTIC_OFFSITE_PRUNE_QUALIFIED") != "true")
        except Exception as exc:
            results[str(backend["id"])] = {"status": "failed", "error": str(exc)}
    return results


def _reconcile_catalogue(adapter: ResticAdapter, env: dict[str, str]) -> int:
    """Forget SQL rows only after both independent repositories forgot them."""
    local = {snapshot["id"] for snapshot in adapter.snapshots()}
    remote = {snapshot["id"] for snapshot in adapter.snapshots(remote=True)} if adapter.config.remote_repository else set()
    count = offset = 0
    candidates: list[str] = []
    while True:
        rows, total = backup_store.list_backups(limit=100, offset=offset)
        for row in rows:
            verification = row.get("verification_json") or {}
            if not is_repository_backup(row) or row.get("storage_backend_id") != env.get("BACKUP_STORAGE_BACKEND_ID"):
                continue
            if row.get("status") != "completed" or (verification.get("activity") or {}).get("active"):
                continue
            if (verification.get("offsite") or {}).get("status") in {"pending", "failed"} or not verification.get("snapshot_id"):
                continue
            if adapter.config.remote_repository and not verification.get("remote_snapshot_id") and (verification.get("offsite") or {}).get("status") != "not_requested":
                continue
            if verification.get("snapshot_id") not in local and verification.get("remote_snapshot_id") not in remote:
                candidates.append(str(row["id"]))
        offset += len(rows)
        if not rows or offset >= total:
            break
    for backup_id in candidates:
        count += int(backup_store.delete_backup_record(backup_id))
    return count
