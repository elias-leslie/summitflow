"""Host telemetry must remain owner-only and private at the HTTP boundary."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.access_control import AccessPrincipal
from app.api import monitor


@contextmanager
def _client(role: Literal["owner", "viewer", "none"]) -> Iterator[TestClient]:
    app = FastAPI()

    @app.middleware("http")
    async def principal(request: Request, call_next):
        if role == "none":
            request.state.principal = None
        else:
            request.state.principal = AccessPrincipal(f"{role}@example.test", role, True)
        return await call_next(request)

    app.include_router(monitor.router)
    with TestClient(app) as client:
        yield client


def test_read_and_capture_require_owner(monkeypatch) -> None:
    read = Mock(return_value={"schema": 1, "items": []})
    control = Mock(return_value={"ok": True, "lease_id": "a" * 32})
    monkeypatch.setattr(monitor, "_read", read)
    monkeypatch.setattr(monitor, "_control", control)

    for role in ("viewer", "none"):
        with _client(role) as client:
            assert client.get("/api/monitor/v1/status").status_code == 403
            assert client.post("/api/monitor/v1/capture").status_code == 403
    read.assert_not_called()
    control.assert_not_called()

    with _client("owner") as client:
        status = client.get("/api/monitor/v1/status")
        capture = client.post("/api/monitor/v1/capture", headers={"Origin": "http://testserver"})
    assert status.status_code == capture.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert capture.headers["cache-control"] == "no-store"
    read.assert_called_once_with("status", max_bytes=4096)
    control.assert_called_once_with("lease_start", ttl_seconds=30)

    with _client("owner") as client:
        cross_site = client.post("/api/monitor/v1/capture", headers={"Origin": "https://other.example"})
    assert cross_site.status_code == 403
    control.assert_called_once_with("lease_start", ttl_seconds=30)


def test_local_bypass_rejects_forwarded_nonlocal_monitor_callers(monkeypatch) -> None:
    read = Mock(return_value={"schema": 1, "items": []})
    monkeypatch.setattr(monitor, "_read", read)
    app = FastAPI()

    @app.middleware("http")
    async def bypass(request: Request, call_next):
        request.state.principal = AccessPrincipal("local@example.test", "owner", True, True)
        return await call_next(request)

    app.include_router(monitor.router)
    with TestClient(app) as client:
        for forwarded in ("192.168.1.4", "127.0.0.1, 10.0.0.4", "invalid"):
            response = client.get("/api/monitor/v1/status", headers={"X-Forwarded-For": forwarded})
            assert response.status_code == 403
        assert client.get("/api/monitor/v1/status", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 200
    read.assert_called_once()


def test_monitor_maintenance_is_transient_service_unavailable(monkeypatch) -> None:
    class MaintenanceReader:
        def __init__(self, _state_dir):
            pass

        def status(self, **_kwargs):
            raise monitor.MonitorQueryError("monitor store maintenance in progress")

    monkeypatch.setattr(monitor, "MonitorReader", MaintenanceReader)
    with _client("owner") as client:
        response = client.get("/api/monitor/v1/status")
    assert response.status_code == 503
    assert response.json()["detail"] == "Monitor history unavailable"

@pytest.mark.parametrize("path", [
    "/api/monitor/v1/series?metric=cpu_busy_pct",
    "/api/monitor/v1/processes",
    "/api/monitor/v1/events",
    "/api/monitor/v1/logs?service=backend",
    "/api/monitor/v1/sensors",
    "/api/monitor/v1/connections",
    "/api/monitor/v1/system-info",
    "/api/monitor/v1/users",
    "/api/monitor/v1/startup",
    "/api/monitor/v1/apps",
    "/api/monitor/v1/drivers",
    "/api/monitor/v1/disk-space?path=/home/example",
    "/api/monitor/v1/export?since=2026-09-25T00:00:00Z&until=2026-09-25T01:00:00Z",
])
def test_all_diagnostic_routes_reject_viewers(path: str) -> None:
    with _client("viewer") as client:
        response = client.get(path)
    assert response.status_code == 403


def test_extended_diagnostics_owner_and_same_origin(monkeypatch) -> None:
    observe = Mock(return_value={"schema": 1, "items": []})
    replay = Mock(return_value={"schema": 1, "items": []})
    monkeypatch.setattr(monitor, "_observe", observe)
    monkeypatch.setattr(monitor, "_export", replay)
    with _client("owner") as client:
        disk = client.get("/api/monitor/v1/disk-space?path=/home/example")
        export = client.get("/api/monitor/v1/export?since=2026-09-25T00:00:00Z&until=2026-09-25T01:00:00Z")
        denied = client.post("/api/monitor/v1/benchmark", json={"kind": "cpu"},
                             headers={"Origin": "https://other.example"})
        benchmark = client.post("/api/monitor/v1/benchmark", json={"kind": "cpu"},
                                headers={"Origin": "http://testserver"})
    assert disk.status_code == export.status_code == benchmark.status_code == 200
    assert denied.status_code == 403
    assert all(response.headers["cache-control"] == "no-store" for response in (disk, export, benchmark))
    assert observe.call_count == 2
    assert replay.call_count == 1


def test_apps_provider_and_cursor_reach_owner_query(monkeypatch) -> None:
    observe = Mock(return_value={"schema": 1, "items": []})
    monkeypatch.setattr(monitor, "_observe", observe)
    with _client("owner") as client:
        response = client.get("/api/monitor/v1/apps?provider=snap&name=fire&cursor=a1.1234567890abcdef.2&limit=1&max_bytes=2048")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    observe.assert_called_once_with(monitor.query_apps, provider="snap", name="fire",
                                    cursor="a1.1234567890abcdef.2",
                                    limit=1, max_bytes=2048)


def test_extended_diagnostics_reject_viewer_writes() -> None:
    with _client("viewer") as client:
        response = client.post("/api/monitor/v1/benchmark", json={"kind": "cpu"},
                               headers={"Origin": "http://testserver"})
    assert response.status_code == 403


def test_expensive_diagnostics_reject_concurrent_overload() -> None:
    assert monitor._diagnostic_slots.acquire(blocking=False)
    assert monitor._diagnostic_slots.acquire(blocking=False)
    try:
        with _client("owner") as client:
            disk = client.get("/api/monitor/v1/disk-space?path=/home/example")
            replay = client.get("/api/monitor/v1/export?since=2026-09-25T00:00:00Z&until=2026-09-25T01:00:00Z")
            benchmark = client.post("/api/monitor/v1/benchmark", json={"kind": "cpu"},
                                    headers={"Origin": "http://testserver"})
        assert {disk.status_code, replay.status_code, benchmark.status_code} == {429}
    finally:
        monitor._diagnostic_slots.release()
        monitor._diagnostic_slots.release()
