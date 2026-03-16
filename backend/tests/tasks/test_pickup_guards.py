"""Tests for pickup guard conditions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.pickup_guards import check_autonomous_enabled, check_system_health


def _mock_response(data: dict) -> MagicMock:
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.json.return_value = data
    return resp


class TestCheckAutonomousEnabled:
    """Tests for check_autonomous_enabled permission tier validation."""

    @patch("httpx.get")
    def test_allowed_write_tier(self, mock_get: MagicMock) -> None:
        """Write tier permits autonomous execution."""
        mock_get.return_value = _mock_response({"allowed": True, "permission_tier": "write"})
        assert check_autonomous_enabled("proj") is None

    @patch("httpx.get")
    def test_allowed_yolo_tier(self, mock_get: MagicMock) -> None:
        """Yolo tier permits autonomous execution."""
        mock_get.return_value = _mock_response({"allowed": True, "permission_tier": "yolo"})
        assert check_autonomous_enabled("proj") is None

    @patch("httpx.get")
    def test_read_tier_blocked(self, mock_get: MagicMock) -> None:
        """Read-only tier blocks autonomous execution."""
        mock_get.return_value = _mock_response({"allowed": True, "permission_tier": "read"})
        result = check_autonomous_enabled("proj")
        assert result is not None
        assert result["status"] == "disabled"
        assert "read" in result["reason"]

    @patch("httpx.get")
    def test_off_tier_blocked(self, mock_get: MagicMock) -> None:
        """Off tier blocks autonomous execution (even if API says allowed)."""
        mock_get.return_value = _mock_response({"allowed": True, "permission_tier": "off"})
        result = check_autonomous_enabled("proj")
        assert result is not None
        assert result["status"] == "disabled"

    @patch("httpx.get")
    def test_not_allowed_returns_disabled(self, mock_get: MagicMock) -> None:
        """API returning allowed=false blocks dispatch."""
        mock_get.return_value = _mock_response({"allowed": False, "reason": "auto_exec_disabled"})
        result = check_autonomous_enabled("proj")
        assert result is not None
        assert result["reason"] == "auto_exec_disabled"

    @patch("httpx.get")
    def test_unreachable_returns_disabled(self, mock_get: MagicMock) -> None:
        """Network failure blocks dispatch."""
        mock_get.side_effect = ConnectionError("down")
        result = check_autonomous_enabled("proj")
        assert result is not None
        assert "unreachable" in result["reason"]


class TestCheckSystemHealth:
    """Tests for check_system_health backend HTTP check."""

    @patch("app.tasks.autonomous.pickup_guards.get_connection")
    @patch("httpx.get")
    @patch("redis.Redis")
    def test_backend_healthy_via_http(
        self, mock_redis_cls: MagicMock, mock_get: MagicMock, mock_conn: MagicMock
    ) -> None:
        """Backend health check uses HTTP instead of systemctl."""
        # Postgres healthy
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: s
        mock_conn.return_value.cursor.return_value.__exit__ = lambda s, *a: None

        # Redis healthy
        mock_redis_cls.from_url.return_value.ping.return_value = True

        # Backend HTTP health returns 200
        resp = MagicMock()
        resp.status_code = 200
        mock_get.return_value = resp

        result = check_system_health("proj")
        assert result is None  # all healthy

    @patch("app.tasks.autonomous.pickup_guards.get_connection")
    @patch("httpx.get")
    @patch("redis.Redis")
    def test_backend_unhealthy_via_http(
        self, mock_redis_cls: MagicMock, mock_get: MagicMock, mock_conn: MagicMock
    ) -> None:
        """Backend returns non-200 marks as unhealthy."""
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: s
        mock_conn.return_value.cursor.return_value.__exit__ = lambda s, *a: None

        mock_redis_cls.from_url.return_value.ping.return_value = True

        resp = MagicMock()
        resp.status_code = 503
        mock_get.return_value = resp

        result = check_system_health("proj")
        assert result is not None
        assert "backend" in result["failing_services"]
