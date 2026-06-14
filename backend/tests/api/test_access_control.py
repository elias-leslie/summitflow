"""Tests for SummitFlow access-control identity resolution."""

from __future__ import annotations

from starlette.requests import Request

from app import access_control


def _request(
    host: str,
    *,
    client_host: str = "127.0.0.1",
    forwarded_host: str | None = None,
) -> Request:
    headers = [(b"host", host.encode())]
    if forwarded_host:
        headers.append((b"x-forwarded-host", forwarded_host.encode()))
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


def test_cloudflare_mode_denies_domain_bypass_from_loopback_proxy(monkeypatch) -> None:
    """A local proxy to the public hostname still needs a Cloudflare token."""
    _configure_cloudflare(monkeypatch)
    monkeypatch.setattr(
        access_control,
        "_local_owner_principal",
        lambda: access_control.AccessPrincipal("owner@example.com", "owner", True, True),
    )

    principal = access_control.resolve_principal(
        _request("localhost:8001", forwarded_host="dev.summitflow.dev")
    )

    assert principal is None


def test_cloudflare_mode_denies_lan_domain_without_token(monkeypatch) -> None:
    """LAN requests to the shared domain must not get owner bypass."""
    _configure_cloudflare(monkeypatch)

    principal = access_control.resolve_principal(
        _request("dev.summitflow.dev", client_host="192.168.8.20")
    )

    assert principal is None
