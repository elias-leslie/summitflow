"""Tests for notification delivery via Web Push."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notifications.delivery import deliver


def _make_notification(
    severity: str = "error",
    task_id: str | None = "t-test-123",
    title: str = "Test Notification",
    message: str = "Something happened",
    notification_id: str = "notif-test-001",
) -> dict[str, Any]:
    """Build a notification dict matching storage layer output."""
    return {
        "id": notification_id,
        "project_id": "test-project",
        "task_id": task_id,
        "type": "task_failed",
        "title": title,
        "message": message,
        "severity": severity,
        "status": "pending",
        "metadata": {},
    }


_MOCK_SUB = {
    "id": "sub-1",
    "endpoint": "https://fcm.googleapis.com/wp/test",
    "p256dh_key": "test-key",
    "auth_key": "test-auth",
}


class TestDeliver:
    """Tests for deliver() dispatcher."""

    @pytest.mark.asyncio
    async def test_deliver_info_no_push(self) -> None:
        """Info notifications stay in-app only — no push."""
        notification = _make_notification(severity="info")

        with patch(
            "app.services.notifications.delivery.web_push.send",
            new_callable=AsyncMock,
        ) as mock_send:
            await deliver(notification)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_deliver_error_sends_web_push(self) -> None:
        """Error notifications are sent via web push."""
        notification = _make_notification(severity="error")
        mock_store = MagicMock()
        mock_store.get_all_subscriptions.return_value = [_MOCK_SUB]

        with (
            patch("app.services.notifications.delivery.push_subscriptions", mock_store),
            patch(
                "app.services.notifications.delivery.web_push.send",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_send.return_value = True
            await deliver(notification)

        mock_send.assert_called_once()
        payload = mock_send.call_args[1]["payload"]
        assert payload["title"] == "Test Notification"
        assert payload["body"] == "Something happened"

    @pytest.mark.asyncio
    async def test_deliver_warning_sends_web_push(self) -> None:
        """Warning notifications trigger push delivery."""
        notification = _make_notification(severity="warning")
        mock_store = MagicMock()
        mock_store.get_all_subscriptions.return_value = [_MOCK_SUB]

        with (
            patch("app.services.notifications.delivery.push_subscriptions", mock_store),
            patch(
                "app.services.notifications.delivery.web_push.send",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_send.return_value = True
            await deliver(notification)

        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_deliver_critical_sends_web_push(self) -> None:
        """Critical notifications trigger push delivery."""
        notification = _make_notification(severity="critical")
        mock_store = MagicMock()
        mock_store.get_all_subscriptions.return_value = [_MOCK_SUB]

        with (
            patch("app.services.notifications.delivery.push_subscriptions", mock_store),
            patch(
                "app.services.notifications.delivery.web_push.send",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_send.return_value = True
            await deliver(notification)

        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_deliver_no_subscriptions_skips(self) -> None:
        """No subscriptions means no push attempted."""
        notification = _make_notification(severity="error")
        mock_store = MagicMock()
        mock_store.get_all_subscriptions.return_value = []

        with (
            patch("app.services.notifications.delivery.push_subscriptions", mock_store),
            patch(
                "app.services.notifications.delivery.web_push.send",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            await deliver(notification)

        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_deliver_payload_includes_task_url(self) -> None:
        """Push payload includes deep-link URL to task."""
        notification = _make_notification(task_id="t-test-789")
        mock_store = MagicMock()
        mock_store.get_all_subscriptions.return_value = [_MOCK_SUB]

        with (
            patch("app.services.notifications.delivery.push_subscriptions", mock_store),
            patch(
                "app.services.notifications.delivery.web_push.send",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_send.return_value = True
            await deliver(notification)

        payload = mock_send.call_args[1]["payload"]
        assert "t-test-789" in payload["url"]

    @pytest.mark.asyncio
    async def test_deliver_sends_to_multiple_devices(self) -> None:
        """Delivery sends to all registered subscriptions."""
        notification = _make_notification(severity="error")
        sub2 = {**_MOCK_SUB, "id": "sub-2", "endpoint": "https://fcm.googleapis.com/wp/test2"}
        mock_store = MagicMock()
        mock_store.get_all_subscriptions.return_value = [_MOCK_SUB, sub2]

        with (
            patch("app.services.notifications.delivery.push_subscriptions", mock_store),
            patch(
                "app.services.notifications.delivery.web_push.send",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_send.return_value = True
            await deliver(notification)

        assert mock_send.call_count == 2
