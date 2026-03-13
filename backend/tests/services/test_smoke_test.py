"""Tests for production smoke test service."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.services.smoke_test import (
    HEALTH_URLS,
    run_all_smoke_tests,
)


class TestRunAllSmokeTests:
    """Tests for the run_all_smoke_tests orchestrator."""

    @patch("app.services.smoke_test.check_health")
    def test_all_healthy(self, mock_check: MagicMock) -> None:
        mock_check.return_value = {"project": "x", "url": "y", "ok": True, "status": "healthy"}

        result = run_all_smoke_tests()

        assert result["total"] == len(HEALTH_URLS)
        assert result["healthy"] == len(HEALTH_URLS)
        assert result["failures"] == []

    @patch("app.services.smoke_test.check_health")
    def test_some_unhealthy(self, mock_check: MagicMock) -> None:
        def side_effect(pid: str, url: str) -> dict[str, Any]:
            if pid == "summitflow":
                return {"project": pid, "url": url, "ok": False, "status": "unhealthy"}
            return {"project": pid, "url": url, "ok": True, "status": "healthy"}

        mock_check.side_effect = side_effect

        result = run_all_smoke_tests()

        assert result["total"] == len(HEALTH_URLS)
        assert len(result["failures"]) == 1
        assert result["failures"][0]["project"] == "summitflow"

    @patch("app.services.smoke_test.check_health")
    def test_all_unhealthy(self, mock_check: MagicMock) -> None:
        mock_check.return_value = {"project": "x", "url": "y", "ok": False, "status": "unhealthy"}

        result = run_all_smoke_tests()

        assert result["healthy"] == 0
        assert len(result["failures"]) == len(HEALTH_URLS)

    def test_health_urls_complete(self) -> None:
        """Verify all expected projects have health URLs."""
        expected = {"summitflow", "agent-hub", "portfolio-ai", "terminal"}
        assert set(HEALTH_URLS.keys()) == expected
