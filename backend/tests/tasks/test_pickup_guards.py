"""Tests for pickup guard conditions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.pickup_guards import check_autonomous_enabled


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
