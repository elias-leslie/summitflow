"""Integrate staged recovery payloads with independent encrypted repositories.

SQL is a catalogue, not the recovery dependency. Private, atomic checkpoints
survive a completed snapshot/copy whose SQL update was interrupted. Plaintext
staging has a stable path for Restic parents and is removed after each attempt.
"""

from __future__ import annotations

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
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from ..services.backup_keys import backup_key_directory
from ..storage import backups as backup_store
from ..utils.shared_paths import get_host_config_root
from .backup_activity import check_backup_cancelled, record_local_archive
from .backup_native_archive import (
    _gzip_payload_file,
    _recoverable_file_filter,
    prepare_project_payload,
)
from .backup_native_infra import prepare_infrastructure_payload
from .backup_native_recovery import GIT_BUNDLE_NAME, RECOVERY_DIR_NAME
from .backup_restic import ResticAdapter, ResticConfig, ResticError
from .backup_utils import (
    REPOSITORY_CRITICAL_RESTORE_DAYS,
    build_storage_env,
    canonical_backup_source_roots,
)


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
    identity = hashlib.sha256((str(config.local_repository.resolve()) + "\n" + (config.remote_repository or "")).encode()).hexdigest()
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
                payload = prepare_project_payload(
                    Path(project_dir), Path(project_dir).name, staging, env,
                    source_roots=canonical_backup_source_roots(), sensitive_paths=(config.key_directory,),
                    git_bundle_reuse=reuse,
                )
            payload["snapshot_dir"].chmod(0o700)
            result = adapter.save_payload(source_id, payload)
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
                "completed_at": datetime.now(UTC).isoformat(),
            }
            state["sources"][source_id] = source_checkpoint
            if not local_only:
                journal = state.setdefault("offsite", {})
                pending = journal.setdefault("pending_snapshot_ids", [])
                if result["snapshot_id"] not in pending:
                    pending.append(result["snapshot_id"])
            _save_json(directory / "state.json", state)
            record_local_archive(result)
            if local_only:
                result["verification"]["offsite"] = {"status": "not_requested"}
            else:
                synced: dict[str, Any]
                try:
                    synced = _sync(adapter, directory, state, result["snapshot_id"])
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


def _sync(adapter: ResticAdapter, directory: Path, state: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    def persist(journal: dict[str, Any]) -> None:
        state["offsite"] = journal
        _save_json(directory / "state.json", state)

    return adapter.sync(snapshot_id, state=state.get("offsite"), persist=persist)


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
        return _sync(adapter, directory, state, snapshot_id)


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
    with tempfile.TemporaryDirectory(prefix="st-repository-restore-") as scratch:
        scratch_path = Path(scratch)
        target = scratch_path / "materialized"
        target.mkdir(mode=0o700)
        restored = adapter.restore(str(snapshot_id), target, remote=remote)
        payload_root = Path(restored["payload_root"])
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
        archive = scratch_path / "recovery.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(payload_root, arcname="infrastructure" if infrastructure else "payload", filter=_recovery_archive_filter)
        archive.chmod(0o600)
        yield archive


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


def maintain_repository(env: dict[str, str], *, dry_run: bool = True) -> dict[str, Any]:
    """Monthly rotating readback, guarded daily expiry and weekly prune.

    Both destructive retention paths stay preview-only before cold recovery is
    qualified. Only forgotten snapshot catalogue rows are reconciled afterwards.
    """
    config = ResticConfig.from_env(env)
    adapter = ResticAdapter(config)
    with _checkpoint(config) as (directory, state):
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
            results["critical_restore"] = _weekly_critical_restore(env, maintenance)
            maintenance["critical_restore_result"] = results["critical_restore"]

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
                previous["monthly"] = check["state"]
                if check["verified"]:
                    previous["monthly_checked_at"] = check["checked_at"]
                previous["monthly_result"] = {key: value for key, value in check.items() if key != "state"}
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
        maintenance["last_run_at"] = now.isoformat()
        maintenance["result"] = results
        _save_json(directory / "state.json", state)
        return results


def _weekly_critical_restore(env: dict[str, str], maintenance: dict[str, Any]) -> dict[str, Any]:
    """Restore essential configuration and databases weekly from offsite only."""
    previous = maintenance.get("critical_restore_at")
    if previous and datetime.fromisoformat(previous) > datetime.now(UTC) - timedelta(days=REPOSITORY_CRITICAL_RESTORE_DAYS):
        return {"status": "skipped", "reason": "weekly-cadence", "verified_at": previous}
    # Conversation trees remain fully backed up and covered by provider hashes
    # and rotating payload checks. Re-downloading them in full every week adds
    # transfer/staging cost without exercising the critical configuration or
    # database rebuilds this drill is intended to verify.
    critical = {"infrastructure", "codex-config", "claude-config", "agent-skills", "claude-user-config"}
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
        return {"status": "pending", "reason": "critical-offsite-coverage-missing", "missing_sources": missing}
    from .backup_executor import _complete_mapped_recovery
    from .backup_native_restore import restore_isolated_archive
    from .backup_restore_drill import _record_drill_result, _run_drill_script

    evidence: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="st-critical-offsite-drill-") as temporary:
        isolated = Path(temporary)
        targets: dict[str, Path] = {}
        for source_id, backup in selected.items():
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
                        restore_isolated_archive(archive, target)
                        targets[source_id] = target
                evidence[source_id] = {"ok": True, "backup_id": backup["id"], "remote_snapshot_id": backup["verification_json"]["remote_snapshot_id"]}
            except Exception as exc:
                if source_id == "infrastructure" and drill_result is None:
                    _record_drill_result(source_id, str(backup["id"]), ok=False, error=str(exc))
                return {"status": "failed", "sources": evidence, "failed_source": source_id, "error": str(exc)}
        for source_id, target in targets.items():
            try:
                mapped = _complete_mapped_recovery(target, {key: root for key, root in targets.items() if key in {"codex-config", "claude-config", "agent-skills"}})
                if not mapped["recovery_complete"]:
                    raise ResticError("Canonical configuration links remain unresolved")
                evidence[source_id].update(mapped)
            except Exception as exc:
                return {"status": "failed", "sources": evidence, "failed_source": source_id, "error": str(exc)}
    maintenance["critical_restore_at"] = datetime.now(UTC).isoformat()
    return {"status": "verified", "verified_at": maintenance["critical_restore_at"], "sources": evidence, "remote_only": True}


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
