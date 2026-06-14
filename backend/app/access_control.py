"""Cloudflare Access identity and SummitFlow authorization."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient, PyJWTError
from starlette.responses import JSONResponse, Response

from .config import settings
from .storage.access import (
    bootstrap_owners,
    get_user,
    list_user_grants,
    normalize_email,
    parse_owner_emails,
)

PUBLIC_API_PREFIXES = ("/api/health",)
PUBLIC_PATHS = {"/health", "/api/auth/me"}
VIEWER_API_PREFIX = "/api/viewer/"


@dataclass(frozen=True)
class AccessPrincipal:
    """Authenticated SummitFlow user identity."""

    email: str
    role: str
    is_active: bool
    is_local_bypass: bool = False

    @property
    def is_owner(self) -> bool:
        return self.role == "owner" and self.is_active

    @property
    def is_viewer(self) -> bool:
        return self.role == "viewer" and self.is_active


def configured_owner_emails() -> set[str]:
    """Return owner emails from configuration."""
    return parse_owner_emails(settings.summitflow_owner_emails)


def bootstrap_configured_owners() -> None:
    """Seed configured owners into the DB."""
    bootstrap_owners(configured_owner_emails())


def get_current_principal(request: Request) -> AccessPrincipal | None:
    """Return the principal attached by middleware."""
    principal = getattr(request.state, "principal", None)
    return principal if isinstance(principal, AccessPrincipal) else None


def require_owner(request: Request) -> AccessPrincipal:
    """Require an active owner."""
    principal = get_current_principal(request)
    if not principal or not principal.is_owner:
        raise HTTPException(status_code=403, detail="Owner access required")
    return principal


def require_authenticated(request: Request) -> AccessPrincipal:
    """Require an authenticated active SummitFlow user."""
    principal = get_current_principal(request)
    if not principal or not principal.is_active:
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


async def access_control_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Attach identity and block viewer mutations/non-viewer APIs."""
    try:
        principal = resolve_principal(request)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    request.state.principal = principal

    path = request.url.path
    if _is_public_path(path):
        return await call_next(request)
    if not path.startswith("/api/"):
        return await call_next(request)

    if principal is None:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)

    if principal.is_owner:
        return await call_next(request)

    if principal.is_viewer and request.method == "GET" and path.startswith(VIEWER_API_PREFIX):
        return await call_next(request)

    if principal.is_viewer:
        return JSONResponse({"detail": "Read-only viewer access"}, status_code=403)

    return JSONResponse({"detail": "SummitFlow user is not authorized"}, status_code=403)


def _is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_API_PREFIXES)


def resolve_principal(request: Request) -> AccessPrincipal | None:
    """Resolve identity from Cloudflare Access or local development bypass."""
    token = _access_token(request)
    if token:
        email = _email_from_cloudflare_token(token)
        return _principal_for_email(email)

    if _cloudflare_configured():
        return None

    return _local_owner_principal()


def _access_token(request: Request) -> str | None:
    header_token = request.headers.get("Cf-Access-Jwt-Assertion", "").strip()
    if header_token:
        return header_token
    cookie_token = request.cookies.get("CF_Authorization", "").strip()
    return cookie_token or None


def _cloudflare_configured() -> bool:
    return bool(settings.cloudflare_access_team_domain and settings.cloudflare_access_aud)


def _email_from_cloudflare_token(token: str) -> str:
    if not _cloudflare_configured():
        raise HTTPException(status_code=503, detail="Cloudflare Access is not configured")
    team_domain = _normalized_team_domain(settings.cloudflare_access_team_domain)
    issuer = f"https://{team_domain}"
    try:
        signing_key = _jwk_client(team_domain).get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.cloudflare_access_aud,
            issuer=issuer,
        )
    except PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid Cloudflare Access token") from exc

    email = _payload_email(payload)
    if not email:
        raise HTTPException(status_code=401, detail="Cloudflare Access token has no email")
    return normalize_email(email)


def _payload_email(payload: dict[str, Any]) -> str | None:
    for key in ("email", "sub"):
        value = payload.get(key)
        if isinstance(value, str) and "@" in value:
            return value
    identity = payload.get("identity")
    if isinstance(identity, dict):
        value = identity.get("email")
        if isinstance(value, str) and "@" in value:
            return value
    return None


def _principal_for_email(email: str) -> AccessPrincipal:
    bootstrap_configured_owners()
    normalized = normalize_email(email)
    owners = configured_owner_emails()
    if normalized in owners and not get_user(normalized):
        bootstrap_owners({normalized})
    user = get_user(normalized)
    if not user:
        return AccessPrincipal(email=normalized, role="none", is_active=False)
    return AccessPrincipal(email=user.email, role=user.role, is_active=user.is_active)


def _local_owner_principal() -> AccessPrincipal:
    owners = configured_owner_emails()
    email = next(iter(sorted(owners)), "local-owner@summitflow.local")
    bootstrap_owners({email})
    return AccessPrincipal(
        email=email,
        role="owner",
        is_active=True,
        is_local_bypass=True,
    )


def _normalized_team_domain(value: str) -> str:
    return value.strip().removeprefix("https://").removeprefix("http://").strip("/")


@lru_cache(maxsize=4)
def _jwk_client(team_domain: str) -> PyJWKClient:
    return PyJWKClient(f"https://{team_domain}/cdn-cgi/access/certs")


def principal_grants(principal: AccessPrincipal) -> list[dict[str, str]]:
    """Return grants visible in /api/auth/me responses."""
    if not principal.is_viewer:
        return []
    return [
        {"project_id": grant.project_id, "section": grant.section}
        for grant in list_user_grants(principal.email)
    ]
