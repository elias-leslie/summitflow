"""Encrypted completed-archive replication through existing Drive transports."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Collection
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from ..services.backup_keys import get_backup_key_paths
from .backup_activity import check_backup_cancelled, current_activity, run_bulk_process
from .backup_native_rclone import NativeRcloneProvider

OFFSITE_MANIFEST_NAME = "offsite-manifest.json"
_ARCHIVE_TIMESTAMP = re.compile(
    r"^(?P<archive>.+-(?P<timestamp>\d{8}-\d{6})\.tar\.gz\.age)"
    r"(?P<suffix>\.parts\.json|\.part\d{6})?$"
)
TRANSFER_TIMEOUT = 600
PART_SIZE_BYTES = 512 * 1024 * 1024


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            check_backup_cancelled()
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _run(command: list[str], *, timeout: int = TRANSFER_TIMEOUT) -> subprocess.CompletedProcess[str]:
    check_backup_cancelled()
    if command[:2] == ["gio", "copy"] or command[0] == "age":
        phase = "encryption" if command[0] == "age" else (
            "verification" if command[-2].startswith("google-drive://") else "upload"
        )
        return run_bulk_process(
            command, env={**os.environ, "LC_ALL": "C"}, phase=phase,
            object_name=Path(command[-1]).name if phase != "upload" else Path(command[-2]).name,
            attention_after=timeout,
        )
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "LC_ALL": "C"},
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _command_error(label: str, result: subprocess.CompletedProcess[str]) -> RuntimeError:
    detail = (result.stderr or result.stdout or "").strip()
    return RuntimeError(f"{label} failed: {detail[-500:] or result.returncode}")


def _safe_source_id(source_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", source_id).strip(".-")
    if not safe:
        raise RuntimeError("Offsite source id is empty after sanitization")
    return safe


def _list_children(uri: str) -> list[dict[str, str]]:
    command = [
        "gio", "list", "-u", "-l", "-a",
        "standard::display-name,standard::type,time::modified", uri,
    ]
    result = _run(command, timeout=60)
    parsed = urlsplit(uri)
    if (
        result.returncode != 0
        and parsed.scheme == "google-drive"
        and parsed.netloc
        and "The specified location is not mounted" in result.stderr
    ):
        # GVfs mounts may disappear after logout/restart while the existing GOA
        # account remains configured. Reuse that account once, without prompts.
        mounted = _run(["gio", "mount", f"google-drive://{parsed.netloc}/"], timeout=60)
        if mounted.returncode != 0:
            raise RuntimeError(
                "Google Drive mount failed; check the existing Google Online Account "
                "connection and sign in there if required. "
                f"{_command_error('GIO mount', mounted)}"
            )
        result = _run(command, timeout=60)
    if result.returncode != 0:
        raise _command_error("GIO list", result)
    children: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        columns = line.split("\t")
        if not columns or not columns[0].strip():
            continue
        attributes = "\t".join(columns[1:])
        display_match = re.search(
            r"standard::display-name=(.*?)(?=\s+[\w-]+::[\w-]+=|\t|$)", attributes,
        )
        children.append(
            {
                "uri": columns[0].strip(),
                "display_name": display_match.group(1).strip() if display_match else "",
                "attributes": attributes,
            }
        )
    return children


def _find_display_child(parent_uri: str, display_name: str) -> str | None:
    matches = [child["uri"] for child in _list_children(parent_uri) if child["display_name"] == display_name]
    if len(matches) > 1:
        raise RuntimeError(f"GIO folder contains duplicate display names: {display_name}")
    return matches[0] if matches else None


def _ensure_display_folder(parent_uri: str, display_name: str) -> str:
    existing = _find_display_child(parent_uri, display_name)
    if existing:
        return existing
    requested_uri = f"{parent_uri.rstrip('/')}/{quote(display_name, safe='')}"
    created = _run(["gio", "mkdir", requested_uri], timeout=60)
    if created.returncode != 0:
        raise _command_error("GIO mkdir", created)
    resolved = _find_display_child(parent_uri, display_name)
    if not resolved:
        raise RuntimeError(f"GIO folder was created but its provider id was not discoverable: {display_name}")
    return resolved


def _write_manifest(local_dir: Path, entry: dict[str, Any]) -> bool:
    local_dir.mkdir(parents=True, exist_ok=True)
    path = local_dir / OFFSITE_MANIFEST_NAME
    payload: dict[str, Any] = {"version": 1, "archives": []}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text())
            if not isinstance(loaded, dict) or not isinstance(loaded.get("archives"), list):
                return False
            payload = loaded
        except (ValueError, OSError):
            return False  # Preserve unknown state for local/remote cleanup.
    archives = payload.get("archives")
    if not isinstance(archives, list):
        archives = []
    archives = [item for item in archives if not isinstance(item, dict) or item.get("archive_name") != entry["archive_name"]]
    archives.insert(0, entry)
    payload["archives"] = archives
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)
    return True


def _pending_archive_names(local_dir: Path) -> set[str]:
    path = local_dir / OFFSITE_MANIFEST_NAME
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text())
        entries = payload.get("archives") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ValueError("Invalid manifest archive list")
        pending: set[str] = set()
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("archive_name"), str)
                or not entry["archive_name"]
            ):
                raise ValueError("Invalid manifest archive entry")
            status = entry.get("status")
            if "status" not in entry:
                # Earlier version-one writers recorded verified copies without
                # a status field. Retain those entries unchanged and protect
                # them conservatively rather than blocking all future rotation.
                if not (
                    isinstance(entry.get("verified_at"), str) and entry["verified_at"]
                    and isinstance(entry.get("remote_uri"), str) and entry["remote_uri"]
                    and isinstance(entry.get("local_checksum"), str)
                    and re.fullmatch(r"sha256:[0-9a-f]{64}", entry["local_checksum"])
                ):
                    raise ValueError("Invalid legacy manifest archive entry")
                status = "pending"
            elif status not in {"pending", "failed", "verified", "unconfigured"}:
                raise ValueError("Invalid manifest archive status")
            if status in {"pending", "failed"}:
                pending.add(entry["archive_name"])
        return pending
    except (OSError, ValueError, TypeError):
        raise RuntimeError("Local offsite manifest state is unknown; remote retention refused") from None


def _apply_remote_retention(
    folder_uri: str,
    retention_days: int,
    preserve_uri: str | None = None,
    pending_archive_names: Collection[str] = (),
) -> list[str]:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    deleted: list[str] = []
    children = _list_children(folder_uri)
    groups: dict[str, tuple[datetime, list[dict[str, str]]]] = {}
    complete: dict[str, datetime] = {}
    for child in children:
        match = _ARCHIVE_TIMESTAMP.fullmatch(child["display_name"])
        if not match:
            continue
        try:
            created = datetime.strptime(match["timestamp"], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            continue  # Not a managed archive timestamp; leave it untouched.
        groups.setdefault(match["archive"], (created, []))[1].append(child)
        if match["suffix"] in {None, ".parts.json"} and match["archive"] not in pending_archive_names:
            complete[match["archive"]] = created
    # Never reclaim incomplete uploads without an available complete archive.
    if not complete:
        return []
    retained = set(sorted(complete, key=lambda name: (complete[name], name), reverse=True)[:3])
    for archive_name, (created, targets) in groups.items():
        # An old retained archive can be retried after an extended outage. Never
        # delete the copy just verified, or the minimum completed recovery points.
        if (
            created >= cutoff
            or any(child["uri"] == preserve_uri for child in targets)
            or archive_name in retained
            or archive_name in pending_archive_names
        ):
            continue
        # Withdraw the completion marker before removing its parts, so a failed
        # cleanup cannot leave a manifest advertising an incomplete archive.
        for target in sorted(targets, key=lambda item: not item["display_name"].endswith(".parts.json")):
            result = _run(["gio", "remove", target["uri"]], timeout=60)
            if result.returncode != 0:
                raise _command_error("GIO retention removal", result)
            deleted.append(target["uri"])
    return deleted


def _download_matches(
    remote_uri: str,
    destination: Path,
    *,
    expected_size: int,
    expected_checksum: str,
) -> tuple[bool, int]:
    """Download one object and compare only after a successful transfer."""
    destination.unlink(missing_ok=True)
    copied = _run(
        ["gio", "copy", "-T", remote_uri, str(destination)],
        timeout=TRANSFER_TIMEOUT,
    )
    if copied.returncode != 0:
        raise _command_error("GIO verification download", copied)
    if not destination.is_file():
        raise RuntimeError("GIO verification download did not create a file")
    downloaded_bytes = destination.stat().st_size
    matches = (
        downloaded_bytes == expected_size
        and _checksum(destination) == expected_checksum
    )
    return matches, downloaded_bytes


def _publish_verified_file(
    local_path: Path,
    *,
    folder_uri: str,
    remote_name: str,
    expected_checksum: str,
    verification_path: Path,
    retry: bool,
    before_replace: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Publish one object and prove its exact bytes through a readback."""
    expected_size = local_path.stat().st_size
    remote_uri = _find_display_child(folder_uri, remote_name)
    preexisting_remote = remote_uri is not None
    uploaded_bytes = 0
    downloaded_bytes = 0

    if remote_uri:
        matches, transferred = _download_matches(
            remote_uri,
            verification_path,
            expected_size=expected_size,
            expected_checksum=expected_checksum,
        )
        downloaded_bytes += transferred
        if matches:
            return {
                "location": remote_uri,
                "uploaded_bytes": 0,
                "downloaded_bytes": downloaded_bytes,
                "reused": True,
            }
        if not retry:
            raise RuntimeError("Offsite verification checksum mismatch")
        if before_replace is not None:
            before_replace()
        removed = _run(["gio", "remove", remote_uri], timeout=60)
        if removed.returncode != 0:
            raise _command_error("GIO stale archive removal", removed)
        remote_uri = None

    if not remote_uri:
        if not preexisting_remote and before_replace is not None:
            before_replace()
        requested_uri = f"{folder_uri.rstrip('/')}/{quote(remote_name, safe='')}"
        uploaded = _run(
            ["gio", "copy", "-T", str(local_path), requested_uri],
            timeout=TRANSFER_TIMEOUT,
        )
        if uploaded.returncode != 0:
            raise _command_error("GIO upload", uploaded)
        remote_uri = _find_display_child(folder_uri, remote_name)
        if not remote_uri:
            raise RuntimeError("Uploaded archive provider id could not be resolved")
        uploaded_bytes = expected_size

    matches, transferred = _download_matches(
        remote_uri,
        verification_path,
        expected_size=expected_size,
        expected_checksum=expected_checksum,
    )
    downloaded_bytes += transferred
    if not matches:
        raise RuntimeError("Offsite verification checksum mismatch")
    return {
        "location": remote_uri,
        "uploaded_bytes": uploaded_bytes,
        "downloaded_bytes": downloaded_bytes,
        "reused": preexisting_remote,
    }


def _replicate_single_file(
    archive_path: Path,
    *,
    source_folder_uri: str,
    local_checksum: str,
    temporary_dir: Path,
    retry: bool,
    provider: NativeRcloneProvider | None = None,
) -> dict[str, Any]:
    publish = provider.publish if provider else _publish_verified_file
    published = publish(
        archive_path,
        folder_uri=source_folder_uri,
        remote_name=archive_path.name,
        expected_checksum=local_checksum,
        verification_path=temporary_dir / "verification-download.age",
        retry=retry,
    )
    return {
        "location": published["location"],
        "transfer_bytes": (
            int(published["uploaded_bytes"])
            + int(published["downloaded_bytes"])
        ),
        **({
            "artifacts": [{
                "role": "archive", "name": archive_path.name,
                "size_bytes": archive_path.stat().st_size, "checksum": local_checksum,
                **{key: published[key] for key in (
                    "location", "provider_id", "remote_path", "provider_checksum", "verification_method",
                )},
            }],
        } if provider else {}),
    }


def _replicate_parts(
    archive_path: Path,
    *,
    source_folder_uri: str,
    local_checksum: str,
    temporary_dir: Path,
    retry: bool,
    on_progress: Callable[[], None] | None = None,
    provider: NativeRcloneProvider | None = None,
) -> dict[str, Any]:
    """Publish a large ciphertext as verified bounded-size objects."""
    aggregate = hashlib.sha256()
    parts: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    transfer_bytes = 0
    manifest_name = f"{archive_path.name}.parts.json"
    completion_withdrawn = False
    publish = provider.publish if provider else _publish_verified_file

    def withdraw_completion() -> None:
        nonlocal completion_withdrawn
        if completion_withdrawn:
            return
        if provider:
            manifest_entry = provider.find(source_folder_uri, manifest_name)
            if manifest_entry:
                provider.remove(source_folder_uri, manifest_entry)
        elif manifest_uri := _find_display_child(source_folder_uri, manifest_name):
            removed = _run(["gio", "remove", manifest_uri], timeout=60)
            if removed.returncode != 0:
                raise _command_error("GIO completion manifest withdrawal", removed)
        completion_withdrawn = True

    with archive_path.open("rb") as source:
        part_number = 0
        while True:
            part_path = temporary_dir / "upload.part"
            part_path.unlink(missing_ok=True)
            part_digest = hashlib.sha256()
            part_bytes = 0
            with part_path.open("wb") as part_file:
                while part_bytes < PART_SIZE_BYTES:
                    chunk = source.read(min(1024 * 1024, PART_SIZE_BYTES - part_bytes))
                    if not chunk:
                        break
                    part_file.write(chunk)
                    part_digest.update(chunk)
                    aggregate.update(chunk)
                    part_bytes += len(chunk)
            if part_bytes == 0:
                part_path.unlink(missing_ok=True)
                break
            part_path.chmod(0o600)
            part_number += 1
            part_name = f"{archive_path.name}.part{part_number:06d}"
            part_checksum = f"sha256:{part_digest.hexdigest()}"
            published = publish(
                part_path,
                folder_uri=source_folder_uri,
                remote_name=part_name,
                expected_checksum=part_checksum,
                verification_path=temporary_dir / "verification-download.part",
                retry=retry,
                before_replace=withdraw_completion if retry else None,
            )
            if on_progress is not None:
                on_progress()
            activity = current_activity()
            if activity:
                activity.verified_part(part_name)
            transfer_bytes += int(published["uploaded_bytes"]) + int(
                published["downloaded_bytes"]
            )
            parts.append(
                {
                    "name": part_name,
                    "size_bytes": part_bytes,
                    "checksum": part_checksum,
                }
            )
            artifacts.append(
                {
                    "role": "part",
                    "name": part_name,
                    "size_bytes": part_bytes,
                    "checksum": part_checksum,
                    "location": published["location"],
                    **({key: published[key] for key in (
                        "provider_id", "remote_path", "provider_checksum", "verification_method",
                    )} if provider else {}),
                }
            )

    aggregate_checksum = f"sha256:{aggregate.hexdigest()}"
    if aggregate_checksum != local_checksum:
        raise RuntimeError("Local archive changed while publishing offsite parts")
    if not parts:
        raise RuntimeError("Offsite parts archive is empty")

    manifest = {
        "version": 1,
        "format": "summitflow-age-parts",
        "archive_name": archive_path.name,
        "size_bytes": sum(part["size_bytes"] for part in parts),
        "checksum": local_checksum,
        "parts": parts,
    }
    manifest_path = temporary_dir / manifest_name
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)
    manifest_checksum = _checksum(manifest_path)
    published_manifest = publish(
        manifest_path,
        folder_uri=source_folder_uri,
        remote_name=manifest_name,
        expected_checksum=manifest_checksum,
        verification_path=temporary_dir / "verification-download.manifest",
        retry=retry,
    )
    transfer_bytes += int(published_manifest["uploaded_bytes"]) + int(
        published_manifest["downloaded_bytes"]
    )
    artifacts.append(
        {
            "role": "manifest",
            "name": manifest_name,
            "size_bytes": manifest_path.stat().st_size,
            "checksum": manifest_checksum,
            "location": published_manifest["location"],
            **({key: published_manifest[key] for key in (
                "provider_id", "remote_path", "provider_checksum", "verification_method",
            )} if provider else {}),
        }
    )
    return {
        "location": published_manifest["location"],
        "layout": "parts-v1",
        "part_count": len(parts),
        "artifacts": artifacts,
        "transfer_bytes": transfer_bytes,
    }


def replicate_completed_archive(
    archive_path: Path,
    *,
    source_id: str,
    local_dir: Path,
    env: dict[str, str],
    retention_days: int,
    retry: bool = False,
    on_progress: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Replicate the exact completed ciphertext and freshly verify each object."""
    started = time.monotonic()
    merged = {**os.environ, **env}
    local_checksum: str | None = None
    try:
        transport = merged.get("BACKUP_OFFSITE_TRANSPORT", "gio").strip().lower()
        if transport not in {"gio", "rclone"}:
            raise RuntimeError("Unsupported native offsite transport")
        root_uri = merged.get("BACKUP_OFFSITE_GIO_URI" if transport == "gio" else "BACKUP_OFFSITE_RCLONE_REMOTE", "").strip()
        if not root_uri:
            if transport == "rclone":
                raise RuntimeError("Native rclone offsite remote is missing")
            return {"status": "unconfigured"}
        if not shutil.which(transport):
            raise RuntimeError(f"{transport} executable is unavailable")
        if not archive_path.name.endswith(".tar.gz.age"):
            raise RuntimeError("offsite replication requires an encrypted .tar.gz.age archive")
        local_checksum = _checksum(archive_path)
        safe_source = _safe_source_id(source_id)
        provider = NativeRcloneProvider(merged) if transport == "rclone" else None
        source_folder_uri = provider.ensure_folder(safe_source) if provider else _ensure_display_folder(root_uri, safe_source)
        with tempfile.TemporaryDirectory(prefix="backup-offsite-") as temporary_dir:
            encrypted_checksum = local_checksum
            encrypted_bytes = archive_path.stat().st_size
            temp_path = Path(temporary_dir)
            replicated = (
                _replicate_parts(
                    archive_path,
                    source_folder_uri=source_folder_uri,
                    local_checksum=local_checksum,
                    temporary_dir=temp_path,
                    retry=retry,
                    on_progress=on_progress,
                    provider=provider,
                )
                if provider is None and encrypted_bytes > PART_SIZE_BYTES
                else _replicate_single_file(
                    archive_path,
                    source_folder_uri=source_folder_uri,
                    local_checksum=local_checksum,
                    temporary_dir=temp_path,
                    retry=retry,
                    provider=provider,
                )
            )
            remote_uri = str(replicated["location"])
        verified_at = datetime.now(UTC).isoformat()
        entry = {
            "status": "verified",
            "archive_name": archive_path.name,
            "source_id": source_id,
            "local_checksum": local_checksum,
            "encrypted_checksum": encrypted_checksum,
            "remote_uri": remote_uri,
            "verified_at": verified_at,
            "transport": transport,
            **{
                key: replicated[key]
                for key in ("layout", "part_count", "artifacts")
                if key in replicated
            },
        }
        protection_error: str | None = None
        try:
            pending_names = _pending_archive_names(local_dir)
            pending_names.discard(archive_path.name)  # This exact copy is now verified.
        except RuntimeError as exc:
            protection_error = str(exc)
            pending_names = set()
        if protection_error is None and not _write_manifest(local_dir, entry):
            protection_error = "Local offsite manifest state is unknown; remote retention refused"
        retention: dict[str, Any] = {"retention_status": "completed", "retention_deleted": 0}
        if provider:
            retention["retention_mode"] = "permanent" if provider.permanent_expiry else "trash"
        try:
            if protection_error:
                raise RuntimeError(protection_error)
            deleted = (
                provider.retention(source_folder_uri, retention_days, remote_uri, _ARCHIVE_TIMESTAMP, pending_names)
                if provider else _apply_remote_retention(source_folder_uri, retention_days, remote_uri, pending_names)
            )
            retention["retention_deleted"] = len(deleted)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            retention.update(retention_status="failed", retention_deleted=None, maintenance_error=str(exc))
        return {
            "status": "verified",
            "transport": transport,
            "location": remote_uri,
            "checksum": encrypted_checksum,
            "local_checksum": local_checksum,
            "verified_at": verified_at,
            **retention,
            "replication_duration_ms": int((time.monotonic() - started) * 1000),
            "encrypted_bytes": encrypted_bytes,
            "transfer_bytes": replicated["transfer_bytes"],
            "reused_local_archive": retry,
            **{
                key: replicated[key]
                for key in ("layout", "part_count", "artifacts")
                if key in replicated
            },
        }
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        failure = {
            "archive_name": archive_path.name,
            "source_id": source_id,
            "local_checksum": local_checksum,
            "status": "failed",
            "error": str(exc),
            "failed_at": datetime.now(UTC).isoformat(),
            "replication_duration_ms": int((time.monotonic() - started) * 1000),
            "reused_local_archive": retry,
        }
        _write_manifest(local_dir, failure)
        return {key: value for key, value in failure.items() if key != "archive_name" and key != "source_id"}


def decrypt_offsite_archive(encrypted_path: Path, output_path: Path, identity_file: Path) -> dict[str, str]:
    """Decrypt a downloaded archive using an explicit, external identity file."""
    if not identity_file.is_file():
        raise RuntimeError("age identity file is missing")
    result = _run(
        ["age", "--decrypt", "-i", str(identity_file), "-o", str(output_path), str(encrypted_path)],
        timeout=TRANSFER_TIMEOUT,
    )
    if result.returncode != 0:
        raise _command_error("age decryption", result)
    return {"archive": str(output_path), "checksum": _checksum(output_path)}


def encrypt_completed_archive(
    plaintext_path: Path,
    encrypted_path: Path,
    env: dict[str, str],
) -> dict[str, str | int]:
    """Encrypt a verified archive before it leaves restrictive staging."""
    started = time.monotonic()
    del env
    recipient_file, _identity_file = get_backup_key_paths(require_validated=True)
    if not shutil.which("age"):
        raise RuntimeError("age executable is unavailable")
    result = _run(
        ["age", "-R", str(recipient_file), "-o", str(encrypted_path), str(plaintext_path)],
        timeout=TRANSFER_TIMEOUT,
    )
    if result.returncode != 0:
        raise _command_error("age encryption", result)
    encrypted_path.chmod(0o600)
    return {
        "content_checksum": _checksum(plaintext_path),
        "checksum": _checksum(encrypted_path),
        "encrypted_bytes": encrypted_path.stat().st_size,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
