"""Tests for Redis-backed health monitor state helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.notifications.health_monitor import _get_last_status


@patch("app.services.notifications.health_monitor.get_redis")
def test_get_last_status_accepts_bytes_payload(mock_get_redis: MagicMock) -> None:
    mock_redis = MagicMock()
    mock_redis.get.return_value = b'{"status":"healthy"}'
    mock_get_redis.return_value = mock_redis

    assert _get_last_status() == "healthy"


@patch("app.services.notifications.health_monitor.get_redis")
def test_get_last_status_returns_none_for_non_json_payload(mock_get_redis: MagicMock) -> None:
    mock_redis = MagicMock()
    mock_redis.get.return_value = object()
    mock_get_redis.return_value = mock_redis

    assert _get_last_status() is None
