"""Tests for production smoke test service."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.services.smoke_test import (
    HEALTH_URLS,
    _build_health_urls,
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


class TestBuildHealthUrls:
    """Tests for dynamic health URL construction based on env vars."""

    def test_always_includes_summitflow(self) -> None:
        urls = _build_health_urls()
        assert "summitflow" in urls

    @patch.dict("os.environ", {}, clear=False)
    def test_no_optional_services_without_env(self) -> None:
        """Without env vars, only summitflow self-health is included."""
        import os

        # Ensure the optional vars are not set
        for var in ("AGENT_HUB_HEALTH_URL", "PORTFOLIO_HEALTH_URL", "TERMINAL_HEALTH_URL"):
            os.environ.pop(var, None)

        urls = _build_health_urls()
        assert set(urls.keys()) == {"summitflow"}

    @patch.dict(
        "os.environ",
        {
            "AGENT_HUB_HEALTH_URL": "http://agent-hub-api:8003/health",
            "PORTFOLIO_HEALTH_URL": "http://portfolio-api:8000/health",
            "TERMINAL_HEALTH_URL": "http://terminal-api:8002/health",
        },
    )
    def test_all_services_with_env(self) -> None:
        """When all env vars are set, all services are included."""
        urls = _build_health_urls()
        assert set(urls.keys()) == {"summitflow", "agent-hub", "portfolio-ai", "terminal"}

    @patch.dict(
        "os.environ",
        {"AGENT_HUB_HEALTH_URL": "http://agent-hub-api:8003/health"},
    )
    def test_partial_profile(self) -> None:
        """Only services with explicit env vars are included."""
        import os

        os.environ.pop("PORTFOLIO_HEALTH_URL", None)
        os.environ.pop("TERMINAL_HEALTH_URL", None)

        urls = _build_health_urls()
        assert set(urls.keys()) == {"summitflow", "agent-hub"}
