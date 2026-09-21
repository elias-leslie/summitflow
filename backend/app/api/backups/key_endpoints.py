"""Authenticated owner API for backup encryption recovery material."""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, SecretStr
from starlette.responses import JSONResponse

from ...access_control import AccessPrincipal, require_owner
from ...logging_config import get_logger
from ...services import backup_keys

logger = get_logger(__name__)
OwnerPrincipal = Annotated[AccessPrincipal, Depends(require_owner)]

_SECRET_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class _SecretSafeRoute(APIRoute):
    """Keep request bodies and secret fields out of validation error responses."""

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def secret_safe_handler(request: Request):
            try:
                return await original_handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={"detail": "Invalid backup encryption request"},
                    headers=_SECRET_HEADERS,
                )
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers={**(exc.headers or {}), **_SECRET_HEADERS},
                )
            except Exception:
                logger.error(
                    "backup_encryption_request_failed",
                    path=request.url.path,
                )
                return JSONResponse(
                    status_code=500,
                    content={"detail": "Backup encryption request failed"},
                    headers=_SECRET_HEADERS,
                )

        return secret_safe_handler


router = APIRouter(route_class=_SecretSafeRoute)


class RecoveryKeyVerifyRequest(BaseModel):
    recovery_key: SecretStr


class RecoveryKeyImportRequest(BaseModel):
    recovery_key: SecretStr


class RecoveryKeyExportResponse(BaseModel):
    key_id: str
    recovery_key: str


def _set_secret_headers(response: Response) -> None:
    for name, value in _SECRET_HEADERS.items():
        response.headers[name] = value


def _authority(value: str | None) -> str:
    if not value:
        return ""
    first = value.split(",", 1)[0].strip().lower()
    parsed = urlparse(first if "://" in first else f"//{first}")
    if not parsed.hostname:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    if port is None or (parsed.scheme == "https" and port == 443) or (
        parsed.scheme == "http" and port == 80
    ):
        return parsed.hostname.lower()
    return f"{parsed.hostname.lower()}:{port}"


def _require_same_origin(request: Request) -> None:
    fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
    if fetch_site == "same-origin":
        return
    origin = request.headers.get("origin", "").strip()
    parsed = urlparse(origin)
    trusted_hosts = {
        _authority(request.url.netloc),
        _authority(request.headers.get("host")),
        _authority(request.headers.get("x-forwarded-host")),
    }
    trusted_hosts.discard("")
    if parsed.scheme in {"http", "https"} and _authority(origin) in trusted_hosts:
        return
    raise HTTPException(
        status_code=403,
        detail="Same-origin request required",
        headers=_SECRET_HEADERS,
    )


def _require_cloudflare_owner(principal: AccessPrincipal) -> None:
    if principal.is_local_bypass:
        raise HTTPException(
            status_code=403,
            detail="Cloudflare Access owner session required for backup recovery keys",
            headers=_SECRET_HEADERS,
        )


def _status(principal: AccessPrincipal) -> dict[str, Any]:
    status = backup_keys.get_backup_key_status()
    return {
        **status,
        "can_manage_key": principal.is_owner and not principal.is_local_bypass,
    }


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, backup_keys.BackupKeyVerificationError):
        return HTTPException(status_code=400, detail=str(exc), headers=_SECRET_HEADERS)
    return HTTPException(status_code=409, detail=str(exc), headers=_SECRET_HEADERS)


@router.get("/backups/encryption")
def backup_encryption_status(
    response: Response,
    principal: OwnerPrincipal,
) -> dict[str, Any]:
    """Return non-secret configuration and recovery-proof status."""
    _set_secret_headers(response)
    return _status(principal)


@router.post("/backups/encryption/setup")
def setup_backup_encryption(
    request: Request,
    response: Response,
    principal: OwnerPrincipal,
) -> dict[str, Any]:
    """Generate the key once without returning private recovery material."""
    _set_secret_headers(response)
    _require_cloudflare_owner(principal)
    _require_same_origin(request)
    try:
        status = backup_keys.setup_backup_key()
    except (backup_keys.BackupKeyUnavailableError, backup_keys.BackupKeyVerificationError) as exc:
        raise _service_error(exc) from None
    logger.info(
        "backup_encryption_key_event",
        action="setup",
        actor=principal.email,
        key_id=status.get("key_id"),
    )
    return {**status, "can_manage_key": True}


@router.post("/backups/encryption/export", response_model=RecoveryKeyExportResponse)
def export_backup_encryption_key(
    request: Request,
    response: Response,
    principal: OwnerPrincipal,
) -> RecoveryKeyExportResponse:
    """Return recovery material only for an explicit same-origin owner action."""
    _set_secret_headers(response)
    _require_cloudflare_owner(principal)
    _require_same_origin(request)
    try:
        key_id, recovery_key = backup_keys.export_backup_recovery_key()
    except (backup_keys.BackupKeyUnavailableError, backup_keys.BackupKeyVerificationError) as exc:
        raise _service_error(exc) from None
    logger.info(
        "backup_encryption_key_event",
        action="export",
        actor=principal.email,
        key_id=key_id,
    )
    return RecoveryKeyExportResponse(key_id=key_id, recovery_key=recovery_key)


@router.post("/backups/encryption/import")
def import_backup_encryption_key(
    payload: RecoveryKeyImportRequest,
    request: Request,
    response: Response,
    principal: OwnerPrincipal,
) -> dict[str, Any]:
    """Install an existing recovery key without replacing configured material."""
    _set_secret_headers(response)
    _require_cloudflare_owner(principal)
    _require_same_origin(request)
    try:
        status = backup_keys.import_backup_recovery_key(
            payload.recovery_key.get_secret_value()
        )
    except (backup_keys.BackupKeyUnavailableError, backup_keys.BackupKeyVerificationError) as exc:
        raise _service_error(exc) from None
    logger.info(
        "backup_encryption_key_event",
        action="import",
        actor=principal.email,
        key_id=status.get("key_id"),
    )
    return {**status, "can_manage_key": True}


@router.post("/backups/encryption/verify")
def verify_backup_encryption_key(
    payload: RecoveryKeyVerifyRequest,
    request: Request,
    response: Response,
    principal: OwnerPrincipal,
) -> dict[str, Any]:
    """Verify pasted/uploaded recovery material with an age round trip."""
    _set_secret_headers(response)
    _require_cloudflare_owner(principal)
    _require_same_origin(request)
    try:
        status = backup_keys.verify_backup_recovery_key(payload.recovery_key.get_secret_value())
    except (backup_keys.BackupKeyUnavailableError, backup_keys.BackupKeyVerificationError) as exc:
        raise _service_error(exc) from None
    logger.info(
        "backup_encryption_key_event",
        action="verify",
        actor=principal.email,
        key_id=status.get("key_id"),
    )
    return {**status, "can_manage_key": True}
