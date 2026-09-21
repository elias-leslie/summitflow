"""Encrypted completed-archive replication through an existing GIO mount."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..services.backup_keys import get_backup_key_paths

OFFSITE_MANIFEST_NAME = "offsite-manifest.json"
_ARCHIVE_TIMESTAMP = re.compile(r"-(\d{8}-\d{6})\.tar\.gz\.age$")
TRANSFER_TIMEOUT = 600


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _run(command: list[str], *, timeout: int = TRANSFER_TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
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
    result = _run(
        [
            "gio",
            "list",
            "-u",
            "-l",
            "-a",
            "standard::display-name,standard::type,time::modified",
            uri,
        ],
        timeout=60,
    )
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


def _write_manifest(local_dir: Path, entry: dict[str, Any]) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    path = local_dir / OFFSITE_MANIFEST_NAME
    payload: dict[str, Any] = {"version": 1, "archives": []}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                payload = loaded
        except (json.JSONDecodeError, OSError):
            pass
    archives = payload.get("archives")
    if not isinstance(archives, list):
        archives = []
    archives = [item for item in archives if not isinstance(item, dict) or item.get("archive_name") != entry["archive_name"]]
    archives.insert(0, entry)
    payload["archives"] = archives
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _apply_remote_retention(folder_uri: str, retention_days: int, preserve_uri: str | None = None) -> list[str]:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    deleted: list[str] = []
    archives: list[tuple[datetime, dict[str, str]]] = []
    for child in _list_children(folder_uri):
        match = _ARCHIVE_TIMESTAMP.search(child["display_name"])
        if not match:
            continue
        created = datetime.strptime(match.group(1), "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
        archives.append((created, child))
    newest_uri = max(archives, key=lambda entry: entry[0])[1]["uri"] if archives else None
    for created, child in archives:
        # An old retained archive can be retried after an extended outage. Never
        # delete the copy just verified, or the last/newest recovery point.
        if created >= cutoff or child["uri"] in {preserve_uri, newest_uri}:
            continue
        result = _run(["gio", "remove", child["uri"]], timeout=60)
        if result.returncode != 0:
            raise _command_error("GIO retention removal", result)
        deleted.append(child["uri"])
    return deleted


def replicate_completed_archive(
    archive_path: Path,
    *,
    source_id: str,
    local_dir: Path,
    env: dict[str, str],
    retention_days: int,
    retry: bool = False,
) -> dict[str, Any]:
    """Upload and download-verify one already encrypted completed archive."""
    started = time.monotonic()
    merged = {**os.environ, **env}
    root_uri = merged.get("BACKUP_OFFSITE_GIO_URI", "").strip()
    if not root_uri:
        return {"status": "unconfigured"}
    if not shutil.which("gio"):
        return {"status": "failed", "error": "gio executable is unavailable"}
    if not archive_path.name.endswith(".tar.gz.age"):
        return {"status": "failed", "error": "offsite replication requires an encrypted .tar.gz.age archive"}

    local_checksum = _checksum(archive_path)
    safe_source = _safe_source_id(source_id)
    try:
        source_folder_uri = _ensure_display_folder(root_uri, safe_source)
        with tempfile.TemporaryDirectory(prefix="backup-offsite-") as temporary_dir:
            encrypted_checksum = local_checksum
            encrypted_bytes = archive_path.stat().st_size
            remote_uri = _find_display_child(source_folder_uri, archive_path.name)
            preexisting_remote = remote_uri is not None
            uploaded_bytes = 0
            if not remote_uri:
                requested_uri = f"{source_folder_uri.rstrip('/')}/{quote(archive_path.name, safe='')}"
                uploaded = _run(
                    ["gio", "copy", "-T", str(archive_path), requested_uri],
                    timeout=TRANSFER_TIMEOUT,
                )
                if uploaded.returncode != 0:
                    raise _command_error("GIO upload", uploaded)
                remote_uri = _find_display_child(source_folder_uri, archive_path.name)
                if not remote_uri:
                    raise RuntimeError("Uploaded archive provider id could not be resolved")
                uploaded_bytes = encrypted_bytes
            downloaded = Path(temporary_dir) / "verification-download.age"
            copied_back = _run(["gio", "copy", "-T", remote_uri, str(downloaded)], timeout=TRANSFER_TIMEOUT)
            verification_download_bytes = downloaded.stat().st_size if downloaded.is_file() else 0
            verification_failed = copied_back.returncode != 0 or (
                downloaded.is_file() and _checksum(downloaded) != encrypted_checksum
            )
            if copied_back.returncode == 0 and not downloaded.is_file():
                verification_failed = True

            if verification_failed and retry and preexisting_remote:
                removed = _run(["gio", "remove", remote_uri], timeout=60)
                if removed.returncode != 0:
                    raise _command_error("GIO stale archive removal", removed)
                requested_uri = f"{source_folder_uri.rstrip('/')}/{quote(archive_path.name, safe='')}"
                uploaded = _run(
                    ["gio", "copy", "-T", str(archive_path), requested_uri],
                    timeout=TRANSFER_TIMEOUT,
                )
                if uploaded.returncode != 0:
                    raise _command_error("GIO replacement upload", uploaded)
                remote_uri = _find_display_child(source_folder_uri, archive_path.name)
                if not remote_uri:
                    raise RuntimeError("Replacement archive provider id could not be resolved")
                uploaded_bytes += encrypted_bytes
                downloaded = Path(temporary_dir) / "replacement-verification-download.age"
                copied_back = _run(
                    ["gio", "copy", "-T", remote_uri, str(downloaded)],
                    timeout=TRANSFER_TIMEOUT,
                )
                verification_download_bytes += (
                    downloaded.stat().st_size if downloaded.is_file() else 0
                )

            if copied_back.returncode != 0:
                raise _command_error("GIO verification download", copied_back)
            if not downloaded.is_file() or _checksum(downloaded) != encrypted_checksum:
                raise RuntimeError("Offsite verification checksum mismatch")
        verified_at = datetime.now(UTC).isoformat()
        entry = {
            "archive_name": archive_path.name,
            "source_id": source_id,
            "local_checksum": local_checksum,
            "encrypted_checksum": encrypted_checksum,
            "remote_uri": remote_uri,
            "verified_at": verified_at,
        }
        _write_manifest(local_dir, entry)
        deleted = _apply_remote_retention(source_folder_uri, retention_days, remote_uri)
        return {
            "status": "verified",
            "location": remote_uri,
            "checksum": encrypted_checksum,
            "local_checksum": local_checksum,
            "verified_at": verified_at,
            "retention_deleted": len(deleted),
            "replication_duration_ms": int((time.monotonic() - started) * 1000),
            "encrypted_bytes": encrypted_bytes,
            "transfer_bytes": uploaded_bytes + verification_download_bytes,
            "reused_local_archive": retry,
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
