"""Tests for health transition notifications."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.notifications.health_monitor import check_and_notify


class TestHealthMonitor:
    """Verify health transition behavior and alert semantics."""

    @patch("app.services.notifications.health_monitor._set_last_status")
    @patch("app.services.notifications.health_monitor._send_transition_notification")
    @patch("app.services.notifications.health_monitor._get_last_status", return_value=None)
    @patch("app.main._check_cache_health")
    @patch("app.main._check_database_health")
    def test_initial_unhealthy_state_triggers_alert(
        self,
        mock_db: MagicMock,
        mock_cache: MagicMock,
        mock_last_status: MagicMock,
        mock_notify: MagicMock,
        mock_set_status: MagicMock,
    ) -> None:
        """A missing Redis state should not suppress the first unhealthy alert."""
        mock_db.return_value = SimpleNamespace(status="unhealthy", message="DB unavailable")
        mock_cache.return_value = SimpleNamespace(status="healthy", message="ok")

        result = check_and_notify()

        assert result["status"] == "unhealthy"
        assert result["action"] == "initial_alert"
        mock_notify.assert_called_once()
        mock_set_status.assert_called_once_with("unhealthy")

    @patch("app.services.notifications.health_monitor._set_last_status")
    @patch("app.services.notifications.health_monitor._send_transition_notification")
    @patch("app.services.notifications.health_monitor._get_last_status", return_value=None)
    @patch("app.main._check_cache_health")
    @patch("app.main._check_database_health")
    def test_initial_healthy_state_does_not_notify(
        self,
        mock_db: MagicMock,
        mock_cache: MagicMock,
        mock_last_status: MagicMock,
        mock_notify: MagicMock,
        mock_set_status: MagicMock,
    ) -> None:
        """Healthy startup state should refresh Redis without spamming notifications."""
        mock_db.return_value = SimpleNamespace(status="healthy", message="ok")
        mock_cache.return_value = SimpleNamespace(status="healthy", message="ok")

        result = check_and_notify()

        assert result["status"] == "healthy"
        assert result["action"] == "no_change"
        mock_notify.assert_not_called()
        mock_set_status.assert_called_once_with("healthy")
