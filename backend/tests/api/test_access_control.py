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


# --- owner by caller identity, not loopback address ---------------------------------------------

import os  # noqa: E402
import socket  # noqa: E402

OWNER = access_control.AccessPrincipal("owner@example.com", "owner", True, is_local_bypass=True)


def _local_request(headers: list[tuple[bytes, bytes]] | None = None, client=("127.0.0.1", 54321)) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/api/auth/me",
            "query_string": b"",
            "headers": [(b"host", b"localhost:8001"), *(headers or [])],
            "client": client,
            "server": ("127.0.0.1", 8001),
        }
    )


def _flag_off(monkeypatch, **settings) -> None:
    monkeypatch.setattr(access_control, "_local_owner_principal", lambda: OWNER)
    monkeypatch.setattr(access_control.settings, "summitflow_loopback_is_owner", False)
    for key, value in settings.items():
        monkeypatch.setattr(access_control.settings, key, value)


def test_flag_on_keeps_every_loopback_caller_owner(monkeypatch) -> None:
    monkeypatch.setattr(access_control, "_local_owner_principal", lambda: OWNER)
    monkeypatch.setattr(access_control, "peer_uid", lambda _r: (_ for _ in ()).throw(AssertionError("no uid lookup")))
    assert access_control.settings.summitflow_loopback_is_owner is True
    assert access_control.resolve_principal(_local_request()) == OWNER


def test_flag_off_loopback_without_a_credential_is_not_owner(monkeypatch) -> None:
    _flag_off(monkeypatch)
    monkeypatch.setattr(access_control, "peer_uid", lambda _r: 4242)
    assert access_control.resolve_principal(_local_request()) is None
    monkeypatch.setattr(access_control, "peer_uid", lambda _r: None)
    assert access_control.resolve_principal(_local_request()) is None


def test_flag_off_owner_user_is_owner_and_agent_user_gets_the_agent_role(monkeypatch) -> None:
    _flag_off(monkeypatch, summitflow_owner_users="1000", summitflow_agent_users="2000,2001")
    monkeypatch.setattr(access_control, "peer_uid", lambda _r: 1000)
    assert access_control.resolve_principal(_local_request()) == OWNER
    monkeypatch.setattr(access_control, "peer_uid", lambda _r: 2001)
    agent = access_control.resolve_principal(_local_request())
    assert agent is not None and agent.is_agent and not agent.is_owner
    monkeypatch.setattr(access_control, "peer_uid", lambda _r: 3000)
    assert access_control.resolve_principal(_local_request()) is None


def test_flag_off_private_lan_callers_get_no_local_identity(monkeypatch) -> None:
    _flag_off(monkeypatch, summitflow_owner_users="1000")
    monkeypatch.setattr(access_control, "peer_uid", lambda _r: 1000)
    assert access_control.resolve_principal(_local_request(client=("192.168.1.9", 5000))) is None


def test_flag_off_owner_token_makes_the_caller_owner(monkeypatch, tmp_path) -> None:
    token_file = tmp_path / "owner-token"
    token_file.write_text("s3cret\n")
    _flag_off(monkeypatch, summitflow_owner_token_file=str(token_file))
    monkeypatch.setattr(access_control, "peer_uid", lambda _r: 4242)
    good = [(b"x-summitflow-owner-token", b"s3cret")]
    bad = [(b"x-summitflow-owner-token", b"nope")]
    assert access_control.resolve_principal(_local_request(good)) == OWNER
    assert access_control.resolve_principal(_local_request(bad)) is None


def test_owner_token_needs_a_readable_file(monkeypatch, tmp_path) -> None:
    _flag_off(monkeypatch, summitflow_owner_token_file=str(tmp_path / "missing"))
    assert access_control.resolve_principal(_local_request([(b"x-summitflow-owner-token", b"x")])) is None


def test_agent_reaches_the_api_but_not_owner_decisions(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    agent = access_control.AccessPrincipal("agent@summitflow.local", "agent", True, is_local_bypass=True)
    monkeypatch.setattr(access_control, "resolve_principal", lambda _request: agent)
    client = TestClient(app)
    assert client.get("/api/viewer/projects").status_code == 404  # past the gate
    assert client.post("/api/backup-storage/x/initialize").status_code == 403
    assert client.get("/api/auth/me").json()["is_owner"] is False


def test_peer_uid_reads_the_socket_owner_from_the_kernel() -> None:
    from app.peer_identity import peer_uid

    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            listener = socket.socket(family)
            listener.bind((host, 0))
        except OSError:
            continue
        listener.listen()
        client = socket.socket(family)
        client.connect(listener.getsockname()[:2])
        conn, _ = listener.accept()
        try:
            request = Request(
                {"type": "http", "headers": [], "client": client.getsockname()[:2], "server": listener.getsockname()[:2]}
            )
            assert peer_uid(request) == os.getuid()
        finally:
            for sock in (client, conn, listener):
                sock.close()
