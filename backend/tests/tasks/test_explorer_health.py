"""Tests for Explorer page health checks."""

from __future__ import annotations

from unittest.mock import patch

from app.tasks.explorer_health import _build_check_base, _check_single_page, _resolve_target_url


def test_build_check_base_rewrites_localhost_for_remote_browser() -> None:
    with patch("app.tasks.explorer_health._runtime_host", return_value="192.168.8.244"):
        assert _build_check_base("http://localhost:3001", 3001) == "http://192.168.8.244:3001"


def test_resolve_target_url_rewrites_scanned_loopback_page_url() -> None:
    page = {
        "id": 12,
        "path": "/settings",
        "metadata": {"url": "http://127.0.0.1:3110/settings"},
    }

    with patch("app.tasks.explorer_health._runtime_host", return_value="192.168.8.244"):
        assert _resolve_target_url(page, "http://192.168.8.244:3001") == "http://192.168.8.244:3110/settings"


def test_check_single_page_prefers_scanned_page_url() -> None:
    """Health checks should use the URL captured by Explorer instead of rebuilding one."""
    page = {
        "id": 12,
        "path": "/settings",
        "metadata": {"url": "http://localhost:3110/settings"},
    }

    with patch(
        "app.tasks.explorer_health._runtime_host",
        return_value="192.168.8.244",
    ), patch(
        "app.tasks.explorer_health.run_ba_check",
        return_value={"pass": True, "checks": {"consoleErrors": {"count": 0, "messages": []}}, "durationMs": 25},
    ) as mock_run, patch(
        "app.tasks.explorer_health.explorer_entries.update_health_check",
        return_value=True,
    ) as mock_update:
        result = _check_single_page(page, "http://localhost:3001")

    mock_run.assert_called_once_with("http://192.168.8.244:3110/settings")
    mock_update.assert_called_once()
    assert result == {"path": "/settings", "status": "healthy", "console_errors": 0}
