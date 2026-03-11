"""Tests for Explorer page health checks."""

from __future__ import annotations

from unittest.mock import patch

from app.tasks.explorer_health import _check_single_page


def test_check_single_page_prefers_scanned_page_url() -> None:
    """Health checks should use the URL captured by Explorer instead of rebuilding one."""
    page = {
        "id": 12,
        "path": "/settings",
        "metadata": {"url": "http://localhost:3110/settings"},
    }

    with patch(
        "app.tasks.explorer_health.run_ba_check",
        return_value={"pass": True, "checks": {"consoleErrors": {"count": 0, "messages": []}}, "durationMs": 25},
    ) as mock_run, patch(
        "app.tasks.explorer_health.explorer_entries.update_health_check",
        return_value=True,
    ) as mock_update:
        result = _check_single_page(page, "http://localhost:3001")

    mock_run.assert_called_once_with("http://localhost:3110/settings")
    mock_update.assert_called_once()
    assert result == {"path": "/settings", "status": "healthy", "console_errors": 0}
