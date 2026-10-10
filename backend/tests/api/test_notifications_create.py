"""Tests for POST /api/projects/{project_id}/notifications."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import notifications as notifications_api
from app.main import app

client = TestClient(app)

_STORED = {
    "id": "n-1",
    "project_id": "agent-hub",
    "task_id": None,
    "type": "system",
    "severity": "error",
    "title": "Host maintenance warning",
    "message": "disk",
    "status": "pending",
    "metadata": {"dedupe_key": "host-guardian:warning"},
    "created_at": datetime(2026, 10, 10, tzinfo=UTC),
    "read_at": None,
    "dismissed_at": None,
}


def _payload(**extra: Any) -> dict[str, Any]:
    return {"type": "system", "title": "Host maintenance warning", "message": "disk",
            "severity": "error", "metadata": {"source": "host-guardian"}, **extra}


def test_create_passes_dedupe_key_and_returns_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_create(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return _STORED

    monkeypatch.setattr(notifications_api.notification_store, "create_notification", fake_create)
    resp = client.post("/api/projects/agent-hub/notifications",
                       json=_payload(dedupe_key="host-guardian:warning"))
    assert resp.status_code == 200
    assert resp.json()["id"] == "n-1"
    assert seen["dedupe_key"] == "host-guardian:warning"


def test_deduplicated_create_returns_204_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notifications_api.notification_store, "create_notification",
                        lambda **_: {})
    resp = client.post("/api/projects/agent-hub/notifications", json=_payload())
    assert resp.status_code == 204
    assert resp.content == b""
