"""Tests for notification delivery via Agent Hub push service."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

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


class TestDeliver:
    """Tests for deliver() dispatcher."""

    @pytest.mark.asyncio
    async def test_deliver_info_no_push(self) -> None:
        """Info notifications stay in-app only — no push."""
        notification = _make_notification(severity="info")

        with patch("app.services.notifications.delivery.httpx.AsyncClient") as mock_client_cls:
            await deliver(notification)
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_deliver_error_calls_agent_hub(self) -> None:
        """Error notifications are sent via Agent Hub push API."""
        notification = _make_notification(severity="error")

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "sent", "delivered": 1}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            await deliver(notification)

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "/api/push/send" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["title"] == "Test Notification"
        assert payload["body"] == "Something happened"
        assert payload["project_id"] == "summitflow"

    @pytest.mark.asyncio
    async def test_deliver_warning_calls_agent_hub(self) -> None:
        """Warning notifications trigger push delivery."""
        notification = _make_notification(severity="warning")

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "sent", "delivered": 1}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            await deliver(notification)

        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_deliver_payload_includes_task_url(self) -> None:
        """Push payload includes deep-link URL to task."""
        notification = _make_notification(task_id="t-test-789")

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "sent", "delivered": 1}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            await deliver(notification)

        payload = mock_client.post.call_args[1]["json"]
        assert "t-test-789" in payload["url"]

    @pytest.mark.asyncio
    async def test_deliver_handles_agent_hub_error(self) -> None:
        """Delivery handles Agent Hub errors gracefully."""
        notification = _make_notification(severity="error")

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            # Should not raise
            await deliver(notification)

    @pytest.mark.asyncio
    async def test_deliver_handles_network_error(self) -> None:
        """Delivery handles network errors gracefully."""
        notification = _make_notification(severity="error")

        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            # Should not raise
            await deliver(notification)
