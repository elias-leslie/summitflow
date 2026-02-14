"""Tests for notification delivery dispatcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.notifications.delivery import deliver


def _make_notification(
    severity: str = "error",
    task_id: str | None = "t-test-123",
    title: str = "Test Notification",
    message: str = "Something happened",
    notification_id: str = "notif-test-001",
) -> dict:
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


class TestDeliver:
    """Tests for deliver() dispatcher."""

    @pytest.mark.asyncio
    async def test_deliver_critical_sends_priority_5(self) -> None:
        """Critical notifications are sent with max priority."""
        notification = _make_notification(severity="critical")

        with patch("app.services.notifications.delivery.ntfy.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await deliver(notification)

        mock_send.assert_called_once()
        assert mock_send.call_args[1]["priority"] == 5

    @pytest.mark.asyncio
    async def test_deliver_error_sends_priority_5(self) -> None:
        """Error notifications are sent with max priority."""
        notification = _make_notification(severity="error")

        with patch("app.services.notifications.delivery.ntfy.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await deliver(notification)

        mock_send.assert_called_once()
        assert mock_send.call_args[1]["priority"] == 5

    @pytest.mark.asyncio
    async def test_deliver_warning_sends_priority_3(self) -> None:
        """Warning notifications are sent with normal priority."""
        notification = _make_notification(severity="warning")

        with patch("app.services.notifications.delivery.ntfy.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await deliver(notification)

        mock_send.assert_called_once()
        assert mock_send.call_args[1]["priority"] == 3

    @pytest.mark.asyncio
    async def test_deliver_info_no_push(self) -> None:
        """Info notifications stay in-app only — no ntfy call."""
        notification = _make_notification(severity="info")

        with patch("app.services.notifications.delivery.ntfy.send", new_callable=AsyncMock) as mock_send:
            await deliver(notification)

        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_deliver_task_notification_includes_view_actions(self) -> None:
        """Task-linked notifications include 'view' action buttons."""
        notification = _make_notification(task_id="t-test-456")

        with patch("app.services.notifications.delivery.ntfy.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await deliver(notification)

        call_kwargs = mock_send.call_args[1]
        actions = call_kwargs["actions"]
        assert len(actions) == 1
        assert actions[0]["action"] == "view"
        assert actions[0]["label"] == "Details"
        assert "t-test-456" in actions[0]["url"]

    @pytest.mark.asyncio
    async def test_deliver_no_task_id_omits_actions(self) -> None:
        """Notifications without task_id have no action buttons."""
        notification = _make_notification(task_id=None)

        with patch("app.services.notifications.delivery.ntfy.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await deliver(notification)

        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["actions"] is None

    @pytest.mark.asyncio
    async def test_deliver_click_url_points_to_task(self) -> None:
        """click_url opens the task page in the PWA."""
        notification = _make_notification(task_id="t-test-789")

        with patch("app.services.notifications.delivery.ntfy.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await deliver(notification)

        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["click_url"] == "https://dev.summitflow.dev/tasks/t-test-789"

    @pytest.mark.asyncio
    async def test_deliver_critical_has_rotating_light_tag(self) -> None:
        """Critical notifications get the rotating_light emoji tag."""
        notification = _make_notification(severity="critical")

        with patch("app.services.notifications.delivery.ntfy.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await deliver(notification)

        call_kwargs = mock_send.call_args[1]
        assert "rotating_light" in call_kwargs["tags"]
