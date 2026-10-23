"""Tests for smoke-test Redis status helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.smoke_test import _get_last_status


@patch("app.services.smoke_test.get_redis")
def test_get_last_status_accepts_bytes_payload(mock_get_redis: MagicMock) -> None:
    mock_redis = MagicMock()
    mock_redis.get.return_value = b'{"status":"healthy"}'
    mock_get_redis.return_value = mock_redis

    assert _get_last_status() == "healthy"


@patch("app.services.smoke_test.get_redis")
def test_get_last_status_returns_none_for_invalid_payload(mock_get_redis: MagicMock) -> None:
    mock_redis = MagicMock()
    mock_redis.get.return_value = object()
    mock_get_redis.return_value = mock_redis

    assert _get_last_status() is None


def test_tether_is_not_checked_when_its_socket_is_absent(monkeypatch) -> None:
    from app.services import smoke_test

    monkeypatch.setattr(smoke_test.tether, "socket_present", lambda *_: False)
    assert smoke_test.check_tether_health() is None


def test_tether_socket_that_does_not_answer_fails(monkeypatch) -> None:
    from app.services import smoke_test

    monkeypatch.setattr(smoke_test.tether, "socket_present", lambda *_: True)
    monkeypatch.setattr(smoke_test.tether, "health", lambda **_: None)
    result = smoke_test.check_tether_health()
    assert result is not None and result["project"] == "aico" and result["ok"] is False
    monkeypatch.setattr(smoke_test.tether, "health", lambda **_: {"status": "ok"})
    healthy = smoke_test.check_tether_health()
    assert healthy is not None and healthy["ok"] is True


def test_health_urls_follow_project_health_url_env(monkeypatch) -> None:
    from app.services import smoke_test

    for key in [key for key in smoke_test.os.environ if key.endswith("_HEALTH_URL")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("PORTFOLIO_AI_HEALTH_URL", "http://portfolio-api:8000/health")
    monkeypatch.setenv("AGENT_HUB_HEALTH_URL", "")
    urls = smoke_test._build_health_urls()
    assert urls["summitflow"].endswith("/health")
    assert urls["portfolio-ai"] == "http://portfolio-api:8000/health"
    assert "agent-hub" not in urls
