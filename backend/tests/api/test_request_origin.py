"""Other sites' pages cannot write through the owner's browser (loopback owner or Access cookie)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import access_control, main
from app.access_control import AccessPrincipal, access_control_middleware
from app.request_origin import request_origin_middleware

OWNER = AccessPrincipal(email="owner@example.test", role="owner", is_active=True)


def _client(monkeypatch, base_url: str = "http://testserver") -> tuple[TestClient, list[str]]:
    monkeypatch.setattr(access_control, "_cloudflare_configured", lambda: True)
    monkeypatch.setattr(access_control, "_email_from_cloudflare_token", lambda token: OWNER.email)
    monkeypatch.setattr(access_control, "_principal_for_email", lambda email: OWNER)
    monkeypatch.setattr(
        access_control,
        "_local_owner_principal",
        lambda: AccessPrincipal(email=OWNER.email, role="owner", is_active=True, is_local_bypass=True),
    )
    app = FastAPI()
    calls: list[str] = []

    @app.post("/api/docker/restart/{name}")
    def restart(name: str) -> dict[str, str]:
        calls.append(name)
        return {"restarted": name}

    @app.get("/api/projects")
    def projects() -> list[str]:
        return []

    # Same order as app.main: the origin check wraps access control.
    app.middleware("http")(access_control_middleware)
    app.middleware("http")(request_origin_middleware)
    return TestClient(app, base_url=base_url), calls


CROSS_SITE = [
    {"origin": "https://evil.example", "content-type": "text/plain"},
    {"origin": "null"},
    {"origin": "https://evil.example", "sec-fetch-site": "cross-site"},
    {"sec-fetch-site": "cross-site"},
    {"sec-fetch-site": "same-site", "origin": "https://agent.summitflow.dev"},
    {"origin": "http://testserver", "sec-fetch-site": "cross-site"},
]


@pytest.mark.parametrize("headers", CROSS_SITE)
def test_loopback_owner_write_from_another_site_is_refused(monkeypatch, headers) -> None:
    http, calls = _client(monkeypatch)
    response = http.post("/api/docker/restart/x", headers=headers, content=b"x")
    assert response.status_code == 403
    assert response.json() == {"detail": "Same-origin request required"}
    assert not calls


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_every_unsafe_method_is_guarded(monkeypatch, method) -> None:
    http, _ = _client(monkeypatch)
    response = http.request(method.upper(), "/api/docker/restart/x", headers={"origin": "https://evil.example"})
    assert response.status_code == 403


@pytest.mark.parametrize("headers", CROSS_SITE[:4])
def test_valid_access_cookie_does_not_carry_a_cross_site_write(monkeypatch, headers) -> None:
    http, calls = _client(monkeypatch, base_url="https://dev.summitflow.dev")
    http.cookies.set("CF_Authorization", "valid-owner-jwt")
    response = http.post("/api/docker/restart/x", headers=headers, content=b"x")
    assert response.status_code == 403
    assert not calls


def test_valid_access_cookie_same_origin_write_still_works(monkeypatch) -> None:
    http, calls = _client(monkeypatch, base_url="https://dev.summitflow.dev")
    http.cookies.set("CF_Authorization", "valid-owner-jwt")
    response = http.post(
        "/api/docker/restart/x",
        headers={"origin": "https://dev.summitflow.dev", "sec-fetch-site": "same-origin"},
    )
    assert response.status_code == 200
    assert calls == ["x"]


@pytest.mark.parametrize(
    "headers",
    [
        {},  # st, agents, services: no browser headers
        {"origin": "http://testserver"},
        {"sec-fetch-site": "same-origin"},
    ],
)
def test_same_origin_and_headerless_writes_pass(monkeypatch, headers) -> None:
    http, calls = _client(monkeypatch)
    assert http.post("/api/docker/restart/x", headers=headers).status_code == 200
    assert calls == ["x"]


def test_reads_are_not_affected(monkeypatch) -> None:
    http, _ = _client(monkeypatch)
    response = http.get("/api/projects", headers={"origin": "https://evil.example", "sec-fetch-site": "cross-site"})
    assert response.status_code == 200


def test_app_wraps_access_control_with_the_origin_check() -> None:
    dispatches = [m.kwargs.get("dispatch") for m in main.app.user_middleware]
    assert request_origin_middleware in dispatches
    assert dispatches.index(request_origin_middleware) < dispatches.index(access_control_middleware)
