"""Storage backend management endpoints."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ...storage import backups as backup_store
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
    config = request.config or {}

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
    deleted = backup_store.delete_backend(backend_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Backend {backend_id} not found")
    return {"deleted": True, "backend_id": backend_id}


@router.post("/backup-storage/{backend_id}/test")
async def test_storage_backend(backend_id: str) -> dict[str, object]:
    """Test storage backend connectivity."""
    backend = backup_store.get_backend(backend_id)
    if not backend:
        raise HTTPException(status_code=404, detail=f"Backend {backend_id} not found")

    config = backend.get("config", {})
    if not isinstance(config, dict):
        config = {}

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
                result = subprocess.run(
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

    backup_store.update_test_result(backend_id, success)
    return {"success": success, "message": message, "backend_id": backend_id}
