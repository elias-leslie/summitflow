"""Other sites' pages cannot write through the owner's browser (loopback owner or Access cookie)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import access_control, main
from app.access_control import AccessPrincipal, access_control_middleware
from app.api import db_workbench
from app.request_origin import request_origin_middleware
from app.services.db_workbench import DbWorkbenchStatus

OWNER = AccessPrincipal(email="owner@example.test", role="owner", is_active=True)


def _client(
    monkeypatch, base_url: str = "http://testserver", peer: tuple[str, int] = ("testclient", 50000)
) -> tuple[TestClient, list[str]]:
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

    @app.get("/api/projects/{project_id}/db-workbench/{kind}/{path:path}")
    def workbench(project_id: str, kind: str, path: str) -> dict[str, str]:
        calls.append(f"workbench:{kind}/{path}")
        return {"ran": path}

    # Same order as app.main: the origin check wraps access control.
    app.middleware("http")(access_control_middleware)
    app.middleware("http")(request_origin_middleware)
    return TestClient(app, base_url=base_url, client=peer), calls


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


@pytest.mark.parametrize("dashboard", ["localhost:3001", "127.0.0.1:3001"])
def test_localhost_dashboard_write_through_its_rewrite_passes(monkeypatch, dashboard) -> None:
    # The dashboard calls /api/* on its own origin; Next forwards Origin, X-Forwarded-Host and
    # Sec-Fetch-Site to :8001. Before, it called :8001 directly (same-site) and got 403.
    http, calls = _client(monkeypatch, base_url="http://localhost:8001", peer=("127.0.0.1", 50000))
    response = http.delete(
        "/api/docker/restart/x",
        headers={"origin": f"http://{dashboard}", "x-forwarded-host": dashboard, "sec-fetch-site": "same-origin"},
    )
    assert response.status_code == 405  # route exists only for POST; the guard let it through
    response = http.post(
        "/api/docker/restart/x",
        headers={"origin": f"http://{dashboard}", "x-forwarded-host": dashboard},
    )
    assert response.status_code == 200
    assert calls == ["x"]


def test_direct_write_from_the_localhost_dashboard_port_stays_refused(monkeypatch) -> None:
    # The dashboard no longer calls :8001 directly; such a write is same-site and refused.
    http, calls = _client(monkeypatch, base_url="http://localhost:8001", peer=("127.0.0.1", 50000))
    response = http.delete(
        "/api/docker/restart/x",
        headers={"origin": "http://localhost:3001", "sec-fetch-site": "same-site"},
    )
    assert response.status_code == 403
    assert not calls


@pytest.mark.parametrize("kind", ["api", "proxy", "proxyapi", "static"])
@pytest.mark.parametrize(
    "headers",
    [
        {"sec-fetch-site": "cross-site"},  # <img src=".../db-workbench/api/query?query=...">
        {"sec-fetch-site": "same-site"},
        {"origin": "https://evil.example"},
        {"origin": "null"},
    ],
)
def test_cross_site_get_cannot_reach_the_db_workbench(monkeypatch, kind, headers) -> None:
    http, calls = _client(monkeypatch)
    response = http.get(f"/api/projects/x/db-workbench/{kind}/query?query=select+1", headers=headers)
    assert response.status_code == 403
    assert not calls


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"sec-fetch-site": "same-origin"},  # the dashboard iframe
        {"sec-fetch-site": "none"},  # owner typed or bookmarked the URL
    ],
)
def test_own_db_workbench_gets_still_work(monkeypatch, headers) -> None:
    http, calls = _client(monkeypatch)
    response = http.get("/api/projects/x/db-workbench/api/query?query=select+1", headers=headers)
    assert response.status_code == 200
    assert calls == ["workbench:api/query"]


def _workbench_client(monkeypatch) -> tuple[TestClient, list[str]]:
    """The real db_workbench router behind both middlewares, with a running stub and captured upstream."""
    _client(monkeypatch)  # stub Access and the loopback owner
    status = DbWorkbenchStatus(
        project_id="x",
        running=True,
        installed=True,
        configured=True,
        readonly=True,
        pid=None,
        port=9,
        proxy_url="/api/projects/x/db-workbench/proxy/",
        direct_url="http://127.0.0.1:9",
        shared_with=None,
        started_at=None,
    )
    monkeypatch.setattr(db_workbench, "status_workbench", lambda project_id: status)
    upstream: list[str] = []

    async def send(self, request: httpx.Request, **kwargs) -> httpx.Response:
        upstream.append(str(request.url))
        return httpx.Response(200, content=b"asset", request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    app = FastAPI()
    app.include_router(db_workbench.router, prefix="/api/projects")
    app.middleware("http")(access_control_middleware)
    app.middleware("http")(request_origin_middleware)
    return TestClient(app), upstream


TRAVERSALS = [
    "static/..%2Fapi%2Fquery",
    "static/%2E%2E%2Fapi%2Fquery",
    "static/..%2Fproxyapi%2Fquery",
    "static/.%2E/api/query",
    "static/%252E%252E%252Fapi%252Fquery",
    "static/..%5Capi%5Cquery",
    "static/js/..%2F..%2Fapi%2Fquery",
    "proxy/..%2Fapi%2Fquery",
]


@pytest.mark.parametrize("path", TRAVERSALS)
def test_cross_site_get_cannot_reach_workbench_sql_through_static(monkeypatch, path) -> None:
    http, upstream = _workbench_client(monkeypatch)
    response = http.get(
        f"/api/projects/x/db-workbench/{path}?query=delete+from+x",
        headers={"sec-fetch-site": "cross-site", "origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert not upstream


@pytest.mark.parametrize("path", TRAVERSALS)
def test_workbench_paths_cannot_leave_their_upstream_prefix(monkeypatch, path) -> None:
    http, upstream = _workbench_client(monkeypatch)
    response = http.get(
        f"/api/projects/x/db-workbench/{path}?query=delete+from+x",
        headers={"sec-fetch-site": "same-origin"},
    )
    assert response.status_code == 400
    assert not upstream


def test_traversal_is_refused_before_the_workbench_is_looked_up(monkeypatch) -> None:
    http, upstream = _workbench_client(monkeypatch)
    monkeypatch.setattr(db_workbench, "status_workbench", lambda project_id: pytest.fail("looked up"))
    response = http.get("/api/projects/x/db-workbench/static/..%2Fapi%2Fquery")
    assert response.status_code == 400
    assert not upstream


def test_own_workbench_static_and_api_calls_still_proxy(monkeypatch) -> None:
    http, upstream = _workbench_client(monkeypatch)
    same_origin = {"sec-fetch-site": "same-origin"}
    asset = http.get("/api/projects/x/db-workbench/static/js/app.js", headers=same_origin)
    query = http.get("/api/projects/x/db-workbench/proxyapi/query?query=select+1", headers=same_origin)
    assert (asset.status_code, asset.content) == (200, b"asset")
    assert query.status_code == 200
    assert upstream == [
        "http://127.0.0.1:9/static/js/app.js",
        "http://127.0.0.1:9/api/query?query=select+1",
    ]


def test_app_wraps_access_control_with_the_origin_check() -> None:
    dispatches = [m.kwargs.get("dispatch") for m in main.app.user_middleware]
    assert request_origin_middleware in dispatches
    assert dispatches.index(request_origin_middleware) < dispatches.index(access_control_middleware)
