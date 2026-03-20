"""Tests for notification delivery via Agent Hub push service."""

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
    project_id: str = "test-project",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a notification dict matching storage layer output."""
    return {
        "id": notification_id,
        "project_id": project_id,
        "task_id": task_id,
        "type": "task_failed",
        "title": title,
        "message": message,
        "severity": severity,
        "status": "pending",
        "metadata": metadata or {},
    }


def _mock_push_client() -> tuple[AsyncMock, AsyncMock]:
    """Return (mock_client, mock_response) wired for a successful push."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "sent", "delivered": 1}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client, mock_response


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
    async def test_deliver_warning_no_push(self) -> None:
        """Warning notifications without force_push stay in-app only."""
        notification = _make_notification(severity="warning")

        with patch("app.services.notifications.delivery.httpx.AsyncClient") as mock_client_cls:
            await deliver(notification)
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_deliver_warning_with_force_push(self) -> None:
        """Warning notifications with force_push metadata trigger push."""
        notification = _make_notification(severity="warning", metadata={"force_push": True})
        mock_client, _ = _mock_push_client()

        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            await deliver(notification)

        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_deliver_error_calls_agent_hub(self) -> None:
        """Error notifications are sent via Agent Hub push API."""
        notification = _make_notification(severity="error")
        mock_client, _ = _mock_push_client()

        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            await deliver(notification)

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "/api/push/send" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["title"] == "[Test Project] Test Notification"
        assert payload["body"] == "Something happened"
        assert payload["project_id"] == "test-project"

    @pytest.mark.asyncio
    async def test_deliver_payload_includes_project_prefix(self) -> None:
        """Push payload title includes project display name prefix."""
        notification = _make_notification(project_id="summitflow", title="Task failed: Deploy")
        mock_client, _ = _mock_push_client()

        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            await deliver(notification)

        payload = mock_client.post.call_args[1]["json"]
        assert payload["title"] == "[SF] Task failed: Deploy"

    @pytest.mark.asyncio
    async def test_deliver_payload_includes_blocker_and_recommendation(self) -> None:
        """Push payload body includes blocker summary and recommendation from metadata."""
        notification = _make_notification(
            metadata={"blocker_summary": "Import error in auth.py", "recommendation": "Fix the import path"},
        )
        mock_client, _ = _mock_push_client()

        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            await deliver(notification)

        payload = mock_client.post.call_args[1]["json"]
        assert "Blocker: Import error in auth.py" in payload["body"]
        assert "Next: Fix the import path" in payload["body"]

    @pytest.mark.asyncio
    async def test_deliver_payload_deep_links_to_chat(self) -> None:
        """Push payload URL deep-links to /chat with full routing context."""
        notification = _make_notification(task_id="t-test-789", notification_id="notif-test-456")
        mock_client, _ = _mock_push_client()

        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            await deliver(notification)

        payload = mock_client.post.call_args[1]["json"]
        assert "/chat?" in payload["url"]
        assert "project_id=test-project" in payload["url"]
        assert "task_id=t-test-789" in payload["url"]
        assert "notification_id=notif-test-456" in payload["url"]

    @pytest.mark.asyncio
    async def test_deliver_payload_includes_notification_id(self) -> None:
        """Push payload includes notification_id field for SW forwarding."""
        notification = _make_notification(notification_id="notif-test-777")
        mock_client, _ = _mock_push_client()

        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            await deliver(notification)

        payload = mock_client.post.call_args[1]["json"]
        assert payload["notification_id"] == "notif-test-777"

    @pytest.mark.asyncio
    async def test_deliver_no_task_id_falls_back_to_frontend_url(self) -> None:
        """When task_id is None, URL falls back to frontend root."""
        notification = _make_notification(task_id=None)
        mock_client, _ = _mock_push_client()

        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            await deliver(notification)

        payload = mock_client.post.call_args[1]["json"]
        assert "task_id" not in payload["url"]

    @pytest.mark.asyncio
    async def test_deliver_handles_agent_hub_error(self) -> None:
        """Delivery handles Agent Hub errors gracefully."""
        notification = _make_notification(severity="error")

        mock_response = MagicMock()
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
