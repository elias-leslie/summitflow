"""Tests for SummitFlow access-control identity resolution."""

from __future__ import annotations

from starlette.requests import Request

from app import access_control


def _request(
    host: str,
    *,
    client_host: str = "127.0.0.1",
    forwarded_host: str | None = None,
    cookie_token: str | None = None,
    header_token: str | None = None,
) -> Request:
    headers = [(b"host", host.encode())]
    if forwarded_host:
        headers.append((b"x-forwarded-host", forwarded_host.encode()))
    if cookie_token:
        headers.append((b"cookie", f"CF_Authorization={cookie_token}".encode()))
    if header_token:
        headers.append((b"cf-access-jwt-assertion", header_token.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/api/auth/me",
            "query_string": b"",
            "headers": headers,
            "client": (client_host, 54321),
            "server": ("localhost", 8001),
        }
    )


def _configure_cloudflare(monkeypatch) -> None:
    monkeypatch.setattr(
        access_control.settings,
        "cloudflare_access_team_domain",
        "summitflow.cloudflareaccess.com",
    )
    monkeypatch.setattr(access_control.settings, "cloudflare_access_aud", "audience-tag")


def test_cloudflare_mode_allows_loopback_localhost_bypass(monkeypatch) -> None:
    """Localhost development remains usable when Cloudflare Access is configured."""
    _configure_cloudflare(monkeypatch)
    local_principal = access_control.AccessPrincipal(
        email="owner@example.com",
        role="owner",
        is_active=True,
        is_local_bypass=True,
    )
    monkeypatch.setattr(access_control, "_local_owner_principal", lambda: local_principal)

    principal = access_control.resolve_principal(
        _request("localhost:3001", forwarded_host="localhost:3001")
    )

    assert principal == local_principal


def test_shared_domain_host_without_token_is_not_owner(monkeypatch) -> None:
    """dev.summitflow.dev is not a local host: no Access identity means no principal."""
    _configure_cloudflare(monkeypatch)
    monkeypatch.setattr(
        access_control,
        "_local_owner_principal",
        lambda: (_ for _ in ()).throw(AssertionError("must not grant local owner")),
    )

    for request in (
        _request("dev.summitflow.dev", client_host="127.0.0.1"),
        _request("localhost:8001", client_host="192.168.8.10", forwarded_host="dev.summitflow.dev"),
    ):
        assert access_control.resolve_principal(request) is None


def test_shared_domain_host_uses_cookie_identity(monkeypatch) -> None:
    """A proxied dev.summitflow.dev request resolves the Access cookie, not the bypass."""
    _configure_cloudflare(monkeypatch)
    viewer = access_control.AccessPrincipal(email="viewer@example.com", role="viewer", is_active=True)
    monkeypatch.setattr(access_control, "_email_from_cloudflare_token", lambda _token: "viewer@example.com")
    monkeypatch.setattr(access_control, "_principal_for_email", lambda _email: viewer)

    principal = access_control.resolve_principal(
        _request(
            "localhost:8001",
            forwarded_host="dev.summitflow.dev",
            cookie_token="viewer-cookie",
        )
    )

    assert principal == viewer


def test_missing_cloudflare_config_denies_non_loopback_callers(monkeypatch) -> None:
    """Missing Access config fails closed for anything but loopback development."""
    monkeypatch.setattr(access_control.settings, "cloudflare_access_team_domain", "")
    monkeypatch.setattr(access_control.settings, "cloudflare_access_aud", "")
    local_principal = access_control.AccessPrincipal(
        email="owner@example.com", role="owner", is_active=True, is_local_bypass=True
    )
    monkeypatch.setattr(access_control, "_local_owner_principal", lambda: local_principal)

    assert access_control.resolve_principal(_request("summitflow.dev", client_host="8.8.8.8")) is None
    assert access_control.resolve_principal(_request("dev.summitflow.dev")) is None
    assert access_control.resolve_principal(_request("localhost:8001", client_host="8.8.8.8")) is None
    assert access_control.resolve_principal(_request("localhost:8001")) == local_principal


def test_cloudflare_mode_uses_header_token_before_local_bypass(monkeypatch) -> None:
    """Cloudflare's origin header still wins over local bypass detection."""
    _configure_cloudflare(monkeypatch)
    header_principal = access_control.AccessPrincipal(
        email="viewer@example.com",
        role="viewer",
        is_active=True,
    )
    monkeypatch.setattr(access_control, "_email_from_cloudflare_token", lambda _token: "viewer@example.com")
    monkeypatch.setattr(access_control, "_principal_for_email", lambda _email: header_principal)

    principal = access_control.resolve_principal(
        _request(
            "localhost:8001",
            client_host="192.168.8.10",
            forwarded_host="dev.summitflow.dev",
            header_token="cloudflare-header-token",
        )
    )

    assert principal == header_principal


def test_cloudflare_mode_denies_public_domain_without_token(monkeypatch) -> None:
    """Public requests to the shared domain need Cloudflare identity."""
    _configure_cloudflare(monkeypatch)

    principal = access_control.resolve_principal(
        _request("dev.summitflow.dev", client_host="8.8.8.8")
    )

    assert principal is None


def test_non_owner_identity_is_denied_and_viewer_routes_are_gone(monkeypatch) -> None:
    """Only owners reach private APIs; the retired viewer surface no longer exists."""
    from fastapi.testclient import TestClient

    from app.main import app

    principals = {
        "legacy-viewer": access_control.AccessPrincipal("viewer@example.com", "viewer", True),
        "unknown": access_control.AccessPrincipal("someone@example.com", "none", False),
        "owner": access_control.AccessPrincipal("owner@example.com", "owner", True),
    }
    monkeypatch.setattr(
        access_control,
        "resolve_principal",
        lambda request: principals[request.headers["x-test-identity"]],
    )
    client = TestClient(app)

    for identity in ("legacy-viewer", "unknown"):
        headers = {"x-test-identity": identity}
        assert client.get("/api/projects", headers=headers).status_code == 403
        assert client.get("/api/viewer/projects", headers=headers).status_code == 403

    owner = {"x-test-identity": "owner"}
    assert client.get("/api/viewer/projects", headers=owner).status_code == 404
    assert client.get("/api/projects/summitflow/design-assets", headers=owner).status_code == 404
    me = client.get("/api/auth/me", headers=owner).json()
    assert me == {
        "authenticated": True,
        "email": "owner@example.com",
        "role": "owner",
        "is_owner": True,
        "is_local_bypass": False,
    }
