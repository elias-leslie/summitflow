"""Request usage log: route templates only, no PII, health probes skipped."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.access_log import ACCESS_LOGGER_NAME, AccessLogMiddleware, caller_token


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(record.getMessage()))


@pytest.fixture
def captured() -> Iterator[_Capture]:
    logger = logging.getLogger(ACCESS_LOGGER_NAME)
    handler = _Capture()
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.get("/api/projects/{project_id}/tasks/{task_id}")
    def get_task(project_id: str, task_id: str) -> dict[str, str]:
        return {"ok": task_id}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(cast(Any, AccessLogMiddleware))
    return TestClient(app)


def test_logs_route_template_without_ids_query_or_headers(client: TestClient, captured: _Capture) -> None:
    response = client.get(
        "/api/projects/summitflow/tasks/task-abc123?token=secret-value",
        headers={
            "Authorization": "Bearer secret-token",
            "Cf-Access-Authenticated-User-Email": "owner@example.com",
            "X-Request-Source": "st-cli/context extra",
        },
    )

    assert response.status_code == 200
    assert len(captured.lines) == 1
    line = captured.lines[0]
    assert set(line) == {"ts", "method", "route", "status", "duration_ms", "caller"}
    assert line["route"] == "/api/projects/{project_id}/tasks/{task_id}"
    assert line["method"] == "GET"
    assert line["status"] == 200
    assert line["caller"] == "st-cli/context"
    raw = json.dumps(line)
    for leaked in ("task-abc123", "summitflow", "secret", "owner@example.com", "Bearer"):
        assert leaked not in raw


def test_unmatched_route_and_user_agent_product(client: TestClient, captured: _Capture) -> None:
    client.get("/no/such/thing/42", headers={"User-Agent": "python-httpx/0.28.1"})

    assert captured.lines[0]["route"] == "unmatched"
    assert captured.lines[0]["status"] == 404
    assert captured.lines[0]["caller"] == "python-httpx"


def test_health_probes_are_not_logged(client: TestClient, captured: _Capture) -> None:
    client.get("/api/health")

    assert captured.lines == []


def test_caller_token_drops_emails_and_truncates() -> None:
    def scope(**headers: str) -> dict[str, object]:
        return {"headers": [(k.encode(), v.encode()) for k, v in headers.items()]}

    assert caller_token(scope(**{"x-request-source": "owner@example.com"})) == "redacted"
    assert len(caller_token(scope(**{"user-agent": "x" * 80}))) == 40
    assert caller_token(scope()) == "unknown"


def test_access_logger_does_not_propagate_to_the_app_log() -> None:
    assert logging.getLogger(ACCESS_LOGGER_NAME).propagate is False


def test_importing_the_app_under_pytest_attaches_no_file_handler() -> None:
    import app.main  # noqa: F401

    # pytest attaches its own capture handlers; only a real access.log file matters.
    files = [getattr(handler, "baseFilename", "") for handler in logging.getLogger(ACCESS_LOGGER_NAME).handlers]
    assert not any(name.endswith("access.log") for name in files), files


def test_route_template_survives_http_middleware_in_between(captured: _Capture) -> None:
    app = FastAPI()

    @app.middleware("http")
    async def passthrough(request, call_next):
        return await call_next(request)

    @app.get("/api/items/{item_id}")
    def get_item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    app.add_middleware(cast(Any, AccessLogMiddleware))
    TestClient(app).get("/api/items/abc")

    assert captured.lines[0]["route"] == "/api/items/{item_id}"
