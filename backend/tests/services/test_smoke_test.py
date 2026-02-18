"""Tests for production smoke test service."""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

from app.services.smoke_test import (
    PROD_HEALTH_URLS,
    check_health,
    run_all_smoke_tests,
)


class TestCheckHealth:
    """Tests for individual health endpoint checks."""

    @patch("app.services.smoke_test.subprocess.run")
    def test_healthy_endpoint(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)

        result = check_health("summitflow", "https://example.com/health")

        assert result["ok"] is True
        assert result["status"] == "healthy"
        assert result["project"] == "summitflow"

    @patch("app.services.smoke_test.subprocess.run")
    def test_unhealthy_endpoint(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1)

        result = check_health("summitflow", "https://example.com/health")

        assert result["ok"] is False
        assert result["status"] == "unhealthy"

    @patch("app.services.smoke_test.subprocess.run")
    def test_timeout_returns_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired("cf-curl", 30)

        result = check_health("summitflow", "https://example.com/health")

        assert result["ok"] is False
        assert "error" in result["status"]

    @patch("app.services.smoke_test.subprocess.run")
    def test_missing_cf_curl_returns_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError("cf-curl not found")

        result = check_health("summitflow", "https://example.com/health")

        assert result["ok"] is False
        assert "error" in result["status"]

    @patch("app.services.smoke_test.subprocess.run")
    def test_uses_cf_curl(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        url = "https://devapi.summitflow.dev/health"

        check_health("summitflow", url)

        mock_run.assert_called_once_with(
            ["cf-curl", "-sf", url],
            capture_output=True,
            text=True,
            timeout=30,
        )


class TestRunAllSmokeTests:
    """Tests for the run_all_smoke_tests orchestrator."""

    @patch("app.services.smoke_test.check_health")
    def test_all_healthy(self, mock_check: MagicMock) -> None:
        mock_check.return_value = {"project": "x", "url": "y", "ok": True, "status": "healthy"}

        result = run_all_smoke_tests()

        assert result["total"] == len(PROD_HEALTH_URLS)
        assert result["healthy"] == len(PROD_HEALTH_URLS)
        assert result["failures"] == []

    @patch("app.services.smoke_test.check_health")
    def test_some_unhealthy(self, mock_check: MagicMock) -> None:
        def side_effect(pid: str, url: str) -> dict[str, Any]:
            if pid == "summitflow":
                return {"project": pid, "url": url, "ok": False, "status": "unhealthy"}
            return {"project": pid, "url": url, "ok": True, "status": "healthy"}

        mock_check.side_effect = side_effect

        result = run_all_smoke_tests()

        assert result["total"] == len(PROD_HEALTH_URLS)
        assert len(result["failures"]) == 1
        assert result["failures"][0]["project"] == "summitflow"

    @patch("app.services.smoke_test.check_health")
    def test_all_unhealthy(self, mock_check: MagicMock) -> None:
        mock_check.return_value = {"project": "x", "url": "y", "ok": False, "status": "unhealthy"}

        result = run_all_smoke_tests()

        assert result["healthy"] == 0
        assert len(result["failures"]) == len(PROD_HEALTH_URLS)

    def test_prod_health_urls_complete(self) -> None:
        """Verify all expected projects have health URLs."""
        expected = {"summitflow", "agent-hub", "portfolio-ai", "terminal"}
        assert set(PROD_HEALTH_URLS.keys()) == expected
