"""Tests for ntfy push notification client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.notifications.ntfy import send


@pytest.fixture(autouse=True)
def _enable_ntfy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable ntfy for all tests in this module."""
    monkeypatch.setattr("app.services.notifications.ntfy.settings.ntfy_enabled", True)
    monkeypatch.setattr("app.services.notifications.ntfy.settings.ntfy_url", "http://localhost:2586")
    monkeypatch.setattr("app.services.notifications.ntfy.settings.ntfy_topic", "sf-alerts")
    monkeypatch.setattr("app.services.notifications.ntfy.settings.ntfy_default_priority", 3)


class TestNtfySend:
    """Tests for ntfy send() function."""

    @pytest.mark.asyncio
    async def test_send_success_posts_to_correct_url(self) -> None:
        """Verify POST to localhost:2586/sf-alerts with correct JSON body."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.notifications.ntfy.httpx.AsyncClient", return_value=mock_client):
            result = await send(message="Test alert", title="Build Failed", priority=5)

        assert result is True
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:2586/sf-alerts"
        payload = call_args[1]["json"]
        assert payload["message"] == "Test alert"
        assert payload["title"] == "Build Failed"
        assert payload["priority"] == 5

    @pytest.mark.asyncio
    async def test_send_disabled_makes_no_http_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When ntfy_enabled=False, no HTTP call should be made."""
        monkeypatch.setattr("app.services.notifications.ntfy.settings.ntfy_enabled", False)

        with patch("app.services.notifications.ntfy.httpx.AsyncClient") as mock_client_cls:
            result = await send(message="Should not send")

        assert result is False
        mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_error_does_not_raise(self) -> None:
        """HTTP errors are caught and logged, returning False."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.notifications.ntfy.httpx.AsyncClient", return_value=mock_client):
            result = await send(message="Test alert")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_with_actions_serializes_correctly(self) -> None:
        """Action buttons are included in the JSON payload."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        actions = [
            {"action": "view", "label": "Details", "url": "https://dev.summitflow.dev/tasks/t-123"},
        ]

        with patch("app.services.notifications.ntfy.httpx.AsyncClient", return_value=mock_client):
            result = await send(message="Task failed", actions=actions)

        assert result is True
        payload = mock_client.post.call_args[1]["json"]
        assert payload["actions"] == actions

    @pytest.mark.asyncio
    async def test_send_with_tags_and_click_url(self) -> None:
        """Tags and click_url are included in payload when provided."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.notifications.ntfy.httpx.AsyncClient", return_value=mock_client):
            result = await send(
                message="Warning",
                tags=["warning"],
                click_url="https://dev.summitflow.dev/tasks/t-456",
            )

        assert result is True
        payload = mock_client.post.call_args[1]["json"]
        assert payload["tags"] == ["warning"]
        assert payload["click"] == "https://dev.summitflow.dev/tasks/t-456"

    @pytest.mark.asyncio
    async def test_send_uses_default_priority_when_none(self) -> None:
        """When priority is None, falls back to settings.ntfy_default_priority."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.notifications.ntfy.httpx.AsyncClient", return_value=mock_client):
            await send(message="Test")

        payload = mock_client.post.call_args[1]["json"]
        assert payload["priority"] == 3
