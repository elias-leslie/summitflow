"""Storage backend management endpoints."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ...access_control import require_owner
from ...services.backup_keys import backup_key_directory, get_backup_key_status
from ...storage import backups as backup_store
from ...tasks.backup_restic import ResticAdapter, ResticConfig, ResticError
from ...tasks.backup_utils import storage_config_env
from ...utils import safe_subprocess
from .models import StorageBackendCreate, StorageBackendResponse, StorageBackendUpdate
from .utils import as_object_dict, optional_bool, optional_str, parse_iso_datetime

router = APIRouter()

# Prefer BACKUP_HOST_ROOT (Docker mount) for persistent credential storage
_HOST_ROOT = os.environ.get("BACKUP_HOST_ROOT")
CREDENTIALS_DIR = Path(_HOST_ROOT) if _HOST_ROOT else Path(os.environ.get("HOME", str(Path.home())))


def _write_smb_credentials(username: str, password: str) -> str:
    """Write SMB credentials file and return its path."""
    cred_file = CREDENTIALS_DIR / ".smbcredentials"
    cred_file.write_text(
        f"username={username}\npassword={password}\ndomain=WORKGROUP\n"
    )
    cred_file.chmod(0o600)
    return str(cred_file)


def _local_storage_dir(config: dict[str, object]) -> Path | None:
    """Resolve the directory used by a local storage backend."""
    root_raw = optional_str(config.get("root_path") or config.get("base_path"))
    path_raw = optional_str(config.get("path")) or ""

    if not root_raw and path_raw and Path(path_raw).is_absolute():
        root_raw = path_raw
        path_raw = ""

    if not root_raw:
        return None

    target = Path(root_raw).expanduser()
    if path_raw:
        target = target / path_raw.strip("/")
    return target


def _validate_engine_config(config: dict[str, object], backend_type: str) -> None:
    """Validate repository boundaries and references without reading secrets."""
    engine = config.get("engine", "native")
    if not isinstance(engine, str) or engine not in {"native", "restic"}:
        raise HTTPException(status_code=400, detail="Unsupported backup engine")
    if engine != "restic":
        if any(key.startswith("restic_") for key in config):
            raise HTTPException(status_code=400, detail="Restic settings require engine=restic")
        transport = config.get("offsite_transport", "gio")
        if not isinstance(transport, str) or transport not in {"gio", "rclone"}:
            raise HTTPException(status_code=400, detail="Unsupported offsite transport")
        if transport == "rclone":
            remote = config.get("offsite_rclone_remote")
            if not isinstance(remote, str) or not re.fullmatch(r"[A-Za-z0-9_-]+:[^\x00\r\n?#\\]+", remote):
                raise HTTPException(status_code=400, detail="Offsite requires a bounded rclone folder")
            if any(part in {"", ".", ".."} for part in remote.split(":", 1)[1].split("/")):
                raise HTTPException(status_code=400, detail="Offsite remote root and traversal are refused")
            config_file = config.get("offsite_rclone_config")
            if not isinstance(config_file, str) or any(char in config_file for char in "\x00\r\n"):
                raise HTTPException(status_code=400, detail="Offsite requires a private rclone config-file reference")
            config_path = Path(config_file)
            if not config_path.is_absolute() or config_path.resolve().parent != backup_key_directory().resolve():
                raise HTTPException(status_code=400, detail="Offsite credential reference must be inside the canonical backup-key directory")
        return
    if backend_type != "local":
        raise HTTPException(status_code=400, detail="Restic requires a local storage backend")
    allowed = {
        "engine", "root_path", "base_path", "path", "offsite_gio_uri",
        "restic_local_repository", "restic_remote_repository", "restic_local_password_file",
        "restic_remote_password_file", "restic_rclone_config", "restic_key_directory",
        "restic_lock_directory", "restic_hostname", "restic_offsite_prune_qualified",
        "restic_automatic_maintenance",
    }
    if set(config) - allowed:
        raise HTTPException(status_code=400, detail="Restic accepts repository settings and credential file references only")
    if "restic_automatic_maintenance" in config and not isinstance(config["restic_automatic_maintenance"], bool):
        raise HTTPException(status_code=400, detail="Automatic repository maintenance must be a boolean")
    for key in (
        "restic_local_repository", "restic_local_password_file", "restic_remote_password_file",
        "restic_rclone_config", "restic_key_directory", "restic_lock_directory",
    ):
        value = config.get(key)
        required = key in {"restic_local_repository", "restic_local_password_file", "restic_key_directory"}
        if value is None and not required:
            continue
        if not isinstance(value, str) or not value.strip() or any(char in value for char in "\x00\r\n"):
            raise HTTPException(status_code=400, detail="Restic repository and credential references must be absolute paths")
        if not Path(value).is_absolute() or Path(value).resolve() == Path("/"):
            raise HTTPException(status_code=400, detail="Restic repository and credential references must be bounded absolute paths")
    local = Path(str(config["restic_local_repository"])).resolve()
    key_directory = Path(str(config["restic_key_directory"])).resolve()
    if not key_directory.is_relative_to(backup_key_directory().resolve()):
        raise HTTPException(status_code=400, detail="Restic credentials must be beneath the canonical backup-key directory")
    for key in ("restic_local_password_file", "restic_remote_password_file", "restic_rclone_config"):
        if config.get(key) and Path(str(config[key])).resolve().parent != key_directory:
            raise HTTPException(status_code=400, detail="Restic credential references must be immediately inside their private key directory")
    remote = config.get("restic_remote_repository")
    if remote is None:
        return
    if not isinstance(remote, str) or not remote.strip() or any(char in remote for char in "\x00\r\n"):
        raise HTTPException(status_code=400, detail="Restic remote repository must be a bounded repository reference")
    if not optional_str(config.get("restic_remote_password_file")):
        raise HTTPException(status_code=400, detail="Restic remote repository requires a password-file reference")
    if remote.startswith("rclone:"):
        reference = remote.removeprefix("rclone:")
        if not re.fullmatch(r"[A-Za-z0-9_-]+:[^\x00\r\n?#]+", reference):
            raise HTTPException(status_code=400, detail="Restic remote repository must identify a bounded rclone folder")
        folder = reference.split(":", 1)[1].strip("/")
        if not folder or folder == "." or ".." in folder.split("/") or not optional_str(config.get("restic_rclone_config")):
            raise HTTPException(status_code=400, detail="Restic requires a bounded remote folder and rclone config-file reference")
    else:
        if not Path(remote).is_absolute():
            raise HTTPException(status_code=400, detail="Restic remote must be a bounded rclone folder or absolute fixture repository")
        remote_path = Path(remote).resolve()
        if local == remote_path or local.is_relative_to(remote_path) or remote_path.is_relative_to(local):
            raise HTTPException(status_code=400, detail="Local and remote Restic repositories must be independent and not nested")


def _restic_backend_env(backend_id: str) -> dict[str, str]:
    backend = backup_store.get_backend(backend_id)
    if not backend:
        raise HTTPException(status_code=404, detail=f"Backend {backend_id} not found")
    if not backend.get("enabled"):
        raise HTTPException(status_code=409, detail="Backup storage backend is disabled")
    config = as_object_dict(backend.get("config"))
    _validate_engine_config(config, str(backend.get("backend_type")))
    if config.get("engine") != "restic":
        raise HTTPException(status_code=400, detail="This backend does not use Restic")
    return storage_config_env({**config, "__backend_type": "local", "__backend_id": backend_id})


def _backend_to_response(backend: dict[str, object]) -> StorageBackendResponse:
    """Convert storage backend dict to response model."""
    config = as_object_dict(backend.get("config"))
    return StorageBackendResponse(
        id=str(backend["id"]),
        name=str(backend["name"]),
        backend_type=str(backend["backend_type"]),
        config=config,
        is_default=bool(backend["is_default"]),
        enabled=bool(backend["enabled"]),
        last_test_at=parse_iso_datetime(optional_str(backend.get("last_test_at"))),
        last_test_ok=optional_bool(backend.get("last_test_ok")),
        created_at=parse_iso_datetime(optional_str(backend.get("created_at"))),
        updated_at=parse_iso_datetime(optional_str(backend.get("updated_at"))),
    )


@router.get("/backup-storage", response_model=list[StorageBackendResponse])
async def list_storage_backends() -> list[StorageBackendResponse]:
    """List all storage backends."""
    backends = backup_store.list_backends()
    return [_backend_to_response(b) for b in backends]


@router.post("/backup-storage", response_model=StorageBackendResponse, status_code=201)
async def create_storage_backend(request: StorageBackendCreate) -> StorageBackendResponse:
    """Create a storage backend and optionally generate credentials file."""
    config = dict(request.config or {})
    _validate_engine_config(config, request.backend_type)

    # If SMB password provided, write credentials file
    password = optional_str(config.pop("password", None))
    if password and request.backend_type == "smb":
        config["credentials_file"] = _write_smb_credentials(
            optional_str(config.get("user")) or "backup-svc", password
        )

    backend = backup_store.create_backend(
        name=request.name,
        backend_type=request.backend_type,
        config=config,
        is_default=request.is_default,
    )
    return _backend_to_response(backend)


@router.get("/backup-storage/status")
async def storage_status() -> dict[str, object]:
    """Check if any storage backend is configured (first-run detection)."""
    backends = backup_store.list_backends(enabled_only=True)
    has_backend = len(backends) > 0
    default = backup_store.get_default_backend()
    return {
        "configured": has_backend,
        "backend_count": len(backends),
        "default_backend_id": default["id"] if default else None,
        "default_backend_name": default["name"] if default else None,
    }


@router.get("/backup-storage/{backend_id}", response_model=StorageBackendResponse)
async def get_storage_backend(backend_id: str) -> StorageBackendResponse:
    """Get storage backend details."""
    backend = backup_store.get_backend(backend_id)
    if not backend:
        raise HTTPException(status_code=404, detail=f"Backend {backend_id} not found")
    return _backend_to_response(backend)


@router.put("/backup-storage/{backend_id}", response_model=StorageBackendResponse)
async def update_storage_backend(
    backend_id: str, request: StorageBackendUpdate
) -> StorageBackendResponse:
    """Update storage backend configuration."""
    existing = backup_store.get_backend(backend_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Backend {backend_id} not found")

    fields = request.model_dump(exclude_unset=True)
    candidate_config = as_object_dict(fields.get("config", existing.get("config")))
    _validate_engine_config(candidate_config, str(existing["backend_type"]))
    existing_config = as_object_dict(existing.get("config"))
    if existing_config.get("engine") == "restic" and "config" in fields:
        mutable_policy = {"restic_offsite_prune_qualified", "restic_automatic_maintenance"}
        identity = {key: value for key, value in existing_config.items() if key not in mutable_policy}
        candidate_identity = {key: value for key, value in candidate_config.items() if key not in mutable_policy}
        if identity != candidate_identity and backup_store.backend_has_backups(backend_id):
            raise HTTPException(status_code=409, detail="Retained backups depend on this repository configuration; create a new backend instead")

    # Handle password update for SMB
    if "config" in fields and isinstance(fields["config"], dict):
        password = optional_str(fields["config"].pop("password", None))
        if password:
            existing_config = as_object_dict(existing.get("config"))
            username = (
                optional_str(fields["config"].get("user"))
                or optional_str(existing_config.get("user"))
                or "backup-svc"
            )
            fields["config"]["credentials_file"] = _write_smb_credentials(username, password)

    updated = backup_store.update_backend(backend_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Backend {backend_id} not found")
    return _backend_to_response(updated)


@router.delete("/backup-storage/{backend_id}")
async def delete_storage_backend(backend_id: str) -> dict[str, object]:
    """Remove a storage backend."""
    if not backup_store.get_backend(backend_id):
        raise HTTPException(status_code=404, detail=f"Backend {backend_id} not found")
    if backup_store.backend_has_backups(backend_id):
        raise HTTPException(status_code=409, detail="Retained backups still reference this storage backend")
    deleted = backup_store.delete_backend(backend_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Backend {backend_id} not found")
    return {"deleted": True, "backend_id": backend_id}


@router.post("/backup-storage/{backend_id}/initialize")
async def initialize_storage_repository(backend_id: str, request: Request, local_only: bool = False) -> dict[str, object]:
    """Explicitly initialize the selected pilot repository pair."""
    require_owner(request)
    from ...tasks.backup_repository_runtime import initialize_repository

    try:
        return await asyncio.to_thread(initialize_repository, _restic_backend_env(backend_id), local_only=local_only)
    except (ResticError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/backup-storage/{backend_id}/repository")
async def storage_repository_status(backend_id: str) -> dict[str, object]:
    """Inspect the selected repository without initializing or repairing it."""
    from ...tasks.backup_repository_runtime import repository_status

    try:
        return await asyncio.to_thread(repository_status, _restic_backend_env(backend_id))
    except (ResticError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/backup-storage/{backend_id}/maintenance")
async def maintain_storage_repository(backend_id: str, request: Request, dry_run: bool = True) -> dict[str, object]:
    """Preview repository maintenance unless application is explicitly requested."""
    require_owner(request)
    from ...tasks.backup_repository_runtime import maintain_repository

    try:
        return await asyncio.to_thread(maintain_repository, _restic_backend_env(backend_id), dry_run=dry_run)
    except (ResticError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/backup-storage/{backend_id}/test")
async def test_storage_backend(backend_id: str) -> dict[str, object]:
    """Test storage backend connectivity."""
    backend = backup_store.get_backend(backend_id)
    if not backend:
        raise HTTPException(status_code=404, detail=f"Backend {backend_id} not found")

    config = backend.get("config", {})
    if not isinstance(config, dict):
        config = {}

    if config.get("engine") == "restic":
        try:
            _validate_engine_config(config, str(backend["backend_type"]))
            env = storage_config_env({**config, "__backend_type": backend["backend_type"]})
            adapter = ResticAdapter(ResticConfig.from_env(env))
            readiness = adapter.readiness(local_only=not bool(config.get("restic_remote_repository")))
            success = bool(readiness.get("ready"))
            message = "Restic credential and pinned-binary checks passed" if success else str(readiness.get("error", "Restic is not ready"))
        except (HTTPException, ResticError, OSError, ValueError) as exc:
            success = False
            message = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
        backup_store.update_test_result(backend_id, success)
        return {
            "success": success, "message": message, "backend_id": backend_id,
            "engine": "restic", "local_success": success, "encryption_ready": success,
            "offsite_success": None,
            "offsite_ready": success if config.get("restic_remote_repository") else None,
            "repository_connectivity_checked": False,
        }

    success = False
    message = "Unknown backend type"

    if backend["backend_type"] == "smb":
        host = config.get("host", "")
        share = config.get("share", "")
        smb_path = config.get("path", "")
        cred_file = config.get("credentials_file", str(CREDENTIALS_DIR / ".smbcredentials"))

        if not host or not share:
            message = "Missing host or share in backend config"
        elif not Path(cred_file).exists():
            message = f"Credentials file not found: {cred_file}"
        else:
            # Test by listing the configured path (root ls may be ACL-denied)
            ls_cmd = f"cd {shlex.quote(smb_path)}; ls" if smb_path else "ls"
            try:
                result = safe_subprocess.run(
                    ["smbclient", f"//{host}/{share}", "-A", cred_file, "-c", ls_cmd],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                success = result.returncode == 0
                message = "Connection successful" if success else f"Connection failed: {result.stderr.strip()[:200]}"
            except subprocess.TimeoutExpired:
                message = "Connection timed out (15s)"
            except FileNotFoundError:
                message = "smbclient not installed"
    elif backend["backend_type"] == "local":
        target_dir = _local_storage_dir(config)
        if target_dir is None:
            message = "Missing root_path for local backend"
        else:
            probe = target_dir / f".summitflow-storage-test-{uuid.uuid4().hex}"
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                probe.write_text("ok\n", encoding="utf-8")
                probe.unlink(missing_ok=True)
                success = True
                message = f"Local storage writable: {target_dir}"
            except OSError as exc:
                message = f"Local storage unavailable: {exc}"

    local_success = success
    offsite_uri = optional_str(config.get("offsite_gio_uri"))
    offsite_success: bool | None = None
    offsite_message: str | None = None
    encryption_ready = bool(get_backup_key_status().get("ready"))
    success = local_success and encryption_ready
    if config.get("offsite_transport") == "rclone":
        from ...tasks.backup_native_rclone import probe_rclone_destination
        try:
            probe_rclone_destination(storage_config_env(config))
            offsite_success = True
            offsite_message = "Google Drive reachable through rclone"
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            offsite_success = False
            offsite_message = "rclone destination unavailable; check private configuration and connectivity"
        success = local_success and offsite_success and encryption_ready
        message = f"{message}; {offsite_message}"
    elif offsite_uri:
        try:
            gio_result = safe_subprocess.run(
                ["gio", "list", "-u", offsite_uri],
                capture_output=True,
                text=True,
                timeout=30,
            )
            offsite_success = gio_result.returncode == 0
            offsite_message = (
                "Google Drive reachable"
                if offsite_success
                else f"GIO destination unavailable: {gio_result.stderr.strip()[:200]}"
            )
        except subprocess.TimeoutExpired:
            offsite_success = False
            offsite_message = "GIO destination check timed out (30s)"
        except FileNotFoundError:
            offsite_success = False
            offsite_message = "gio not installed"
        success = local_success and offsite_success and encryption_ready
        message = f"{message}; {offsite_message}"
    if not encryption_ready:
        message = f"{message}; backup recovery key is not verified"

    backup_store.update_test_result(backend_id, success)
    return {
        "success": success,
        "message": message,
        "backend_id": backend_id,
        "local_success": local_success,
        "offsite_success": offsite_success,
        "offsite_message": offsite_message,
        "encryption_ready": encryption_ready,
    }
