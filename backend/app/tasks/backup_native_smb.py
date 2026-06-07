from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StorageConfig:
    host: str
    share: str
    remote_path: str
    user: str
    credentials_file: Path

    @property
    def location_prefix(self) -> str:
        return f"//{self.host}/{self.share}/{self.remote_path}"


@dataclass(frozen=True)
class SmbUploadResult:
    ok: bool
    archive_name: str
    remote_path: str
    location: str
    returncode: int | None = None
    error: str | None = None
    stdout: str = ""
    stderr: str = ""


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _source_remote_path(source_id: str, configured_path: object = None) -> str:
    base = str(configured_path or "").strip().strip("/")
    if not base:
        return f"project-backups/{source_id}"
    if "{source}" in base or "{project}" in base:
        return base.replace("{source}", source_id).replace("{project}", source_id)
    if base.rsplit("/", 1)[-1] == source_id:
        return base
    return f"{base}/{source_id}"


def _storage_config(project_name: str, env: dict[str, str]) -> StorageConfig:
    env_file = _read_env_file(Path.home() / ".env.local")
    merged = {**env_file, **env}
    remote_path = _source_remote_path(project_name, merged.get("SMB_PATH"))
    return StorageConfig(
        host=merged.get("SMB_HOST", ""),
        share=merged.get("SMB_SHARE", ""),
        remote_path=remote_path,
        user=merged.get("SMB_USER", "backup-svc"),
        credentials_file=Path(
            merged.get("CREDENTIALS_FILE", str(Path.home() / ".smbcredentials"))
        ).expanduser(),
    )


def _smb_probe_dir(remote_path: str) -> str:
    parent = remote_path.rsplit("/", 1)[0] if "/" in remote_path else "."
    return parent or "."


def _smb_available(storage: StorageConfig) -> bool:
    if not storage.credentials_file.exists() or not shutil.which("smbclient"):
        return False
    probe_dir = _smb_probe_dir(storage.remote_path)
    result = subprocess.run(
        [
            "smbclient",
            f"//{storage.host}/{storage.share}",
            "-A",
            str(storage.credentials_file),
            "-c",
            f"cd {probe_dir}; ls",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.returncode == 0


def _smb_output(stdout: str, stderr: str, limit: int = 1200) -> str:
    detail = "\n".join(part.strip() for part in (stdout, stderr) if part.strip())
    return detail[-limit:]


def _smb_command(storage: StorageConfig, command: str, *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "smbclient",
            f"//{storage.host}/{storage.share}",
            "-A",
            str(storage.credentials_file),
            "-c",
            command,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _smb_cd_ok(storage: StorageConfig, remote_path: str) -> bool:
    result = _smb_command(storage, f"cd {remote_path}; ls", timeout=30)
    return result.returncode == 0


def _ensure_smb_dir(storage: StorageConfig) -> SmbUploadResult:
    if _smb_cd_ok(storage, storage.remote_path):
        return SmbUploadResult(
            ok=True,
            archive_name="",
            remote_path=storage.remote_path,
            location=storage.location_prefix,
        )

    parts = [part for part in storage.remote_path.split("/") if part]
    current = ""
    last_result: subprocess.CompletedProcess[str] | None = None
    for part in parts:
        current = f"{current}/{part}" if current else part
        last_result = _smb_command(storage, f"mkdir {current}", timeout=30)

    check = _smb_command(storage, f"cd {storage.remote_path}; ls", timeout=30)
    if check.returncode == 0:
        return SmbUploadResult(
            ok=True,
            archive_name="",
            remote_path=storage.remote_path,
            location=storage.location_prefix,
        )

    detail_source = check if check.stdout or check.stderr else last_result
    stdout = detail_source.stdout if detail_source else ""
    stderr = detail_source.stderr if detail_source else ""
    return SmbUploadResult(
        ok=False,
        archive_name="",
        remote_path=storage.remote_path,
        location=storage.location_prefix,
        returncode=check.returncode,
        error=f"remote directory unavailable: {_smb_output(stdout, stderr)}",
        stdout=stdout,
        stderr=stderr,
    )


def _smb_upload(path: Path, archive_name: str, storage: StorageConfig) -> SmbUploadResult:
    if not storage.credentials_file.exists():
        return SmbUploadResult(
            ok=False,
            archive_name=archive_name,
            remote_path=storage.remote_path,
            location=f"{storage.location_prefix}/{archive_name}",
            error=f"credentials file missing: {storage.credentials_file}",
        )
    if not shutil.which("smbclient"):
        return SmbUploadResult(
            ok=False,
            archive_name=archive_name,
            remote_path=storage.remote_path,
            location=f"{storage.location_prefix}/{archive_name}",
            error="smbclient not found",
        )

    directory = _ensure_smb_dir(storage)
    if not directory.ok:
        return SmbUploadResult(
            ok=False,
            archive_name=archive_name,
            remote_path=storage.remote_path,
            location=f"{storage.location_prefix}/{archive_name}",
            returncode=directory.returncode,
            error=directory.error,
            stdout=directory.stdout,
            stderr=directory.stderr,
        )

    command = f'cd {storage.remote_path}; put "{path}" "{archive_name}"; ls "{archive_name}"'
    result = _smb_command(storage, command, timeout=300)
    output = result.stdout + result.stderr
    ok = result.returncode == 0 and archive_name in output
    error = None if ok else f"upload failed rc={result.returncode}: {_smb_output(result.stdout, result.stderr)}"
    return SmbUploadResult(
        ok=ok,
        archive_name=archive_name,
        remote_path=storage.remote_path,
        location=f"{storage.location_prefix}/{archive_name}",
        returncode=result.returncode,
        error=error,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _save_pending(path: Path, archive_name: str, project_name: str, storage: StorageConfig) -> Path:
    pending_dir = Path.home() / ".local" / "share" / "backup-pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    pending = pending_dir / archive_name
    shutil.copy2(path, pending)
    meta = {
        "project": project_name,
        "archive": archive_name,
        "created_at": datetime.now(UTC).isoformat(),
        "smb_host": storage.host,
        "smb_share": storage.share,
        "smb_path": storage.remote_path,
        "retry_count": 0,
    }
    pending.with_suffix(pending.suffix + ".meta").write_text(
        json.dumps(meta, indent=2, sort_keys=True)
    )
    return pending


def _storage_from_pending_meta(meta: dict[str, Any], archive: Path) -> StorageConfig:
    source_id = str(meta.get("project") or archive.stem.rsplit("-", 2)[0] or archive.stem)
    remote_path = _source_remote_path(source_id, meta.get("smb_path"))
    return StorageConfig(
        host=str(meta.get("smb_host") or ""),
        share=str(meta.get("smb_share") or ""),
        remote_path=remote_path,
        user=os.environ.get("SMB_USER", "backup-svc"),
        credentials_file=Path.home() / ".smbcredentials",
    )
