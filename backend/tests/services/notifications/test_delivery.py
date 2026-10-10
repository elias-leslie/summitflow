"""Tests for notification delivery via Agent Hub Telegram."""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notifications.delivery import deliver
from app.storage import notifications as notification_storage


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


def _mock_telegram_client(status_code: int = 200) -> AsyncMock:
    """Return a mock httpx.AsyncClient wired for an Agent Hub Telegram response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.text = "error" if status_code != 200 else ""
    mock_response.json.return_value = {"status": "sent", "chunks": 1}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


async def _sent_payload(notification: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    mock_client = _mock_telegram_client()
    with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
        await deliver(notification)
    mock_client.post.assert_called_once()
    call = mock_client.post.call_args
    return call.args[0], call.kwargs["json"]


class TestDeliver:
    """Tests for deliver() routing and payload."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("severity", ["info", "warning"])
    async def test_low_severity_stays_in_app(self, severity: str) -> None:
        with patch("app.services.notifications.delivery.httpx.AsyncClient") as mock_client_cls:
            await deliver(_make_notification(severity=severity))
        mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_warning_with_force_telegram_is_sent(self) -> None:
        _, payload = await _sent_payload(
            _make_notification(severity="warning", metadata={"force_telegram": True})
        )
        assert payload["title"].startswith("[WARNING] ")

    @pytest.mark.asyncio
    async def test_error_posts_to_agent_hub_telegram(self) -> None:
        url, payload = await _sent_payload(_make_notification(severity="error"))
        assert url.endswith("/api/notifications/telegram")
        assert "/api/push" not in url
        assert payload["title"] == "[ERROR] [Test Project] Test Notification"
        assert payload["severity"] == "error"
        assert payload["source"] == "summitflow"
        assert payload["body"].startswith("Something happened\n")
        assert set(payload) == {"title", "body", "severity", "source"}

    @pytest.mark.asyncio
    async def test_critical_has_critical_prefix_and_project_slug(self) -> None:
        _, payload = await _sent_payload(
            _make_notification(severity="critical", project_id="summitflow", title="Backup failed")
        )
        assert payload["title"] == "[CRITICAL] [SF] Backup failed"
        assert payload["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_body_includes_blocker_recommendation_task_and_link(self) -> None:
        _, payload = await _sent_payload(
            _make_notification(
                task_id="t-test-789",
                notification_id="notif-test-456",
                metadata={"blocker_summary": "Import error in auth.py", "recommendation": "Fix the import path"},
            )
        )
        body = payload["body"]
        assert "Blocker: Import error in auth.py" in body
        assert "Next: Fix the import path" in body
        assert "Task: t-test-789" in body
        assert "/chat?" in body
        assert "notification_id=notif-test-456" in body

    @pytest.mark.asyncio
    async def test_no_task_id_omits_task_line(self) -> None:
        _, payload = await _sent_payload(_make_notification(task_id=None))
        assert "Task:" not in payload["body"]
        assert "task_id=" not in payload["body"]

    @pytest.mark.asyncio
    async def test_payload_respects_endpoint_limits(self) -> None:
        _, payload = await _sent_payload(_make_notification(title="x" * 500, message="y" * 9000))
        assert len(payload["title"]) <= 200
        assert len(payload["body"]) <= 8000

    @pytest.mark.asyncio
    async def test_agent_hub_error_is_swallowed(self) -> None:
        mock_client = _mock_telegram_client(status_code=503)
        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            await deliver(_make_notification())

    @pytest.mark.asyncio
    async def test_network_error_is_swallowed(self) -> None:
        mock_client = _mock_telegram_client()
        mock_client.post.side_effect = Exception("Connection refused")
        with patch("app.services.notifications.delivery.httpx.AsyncClient", return_value=mock_client):
            await deliver(_make_notification())


class TestScheduleDelivery:
    """Sync storage callers must deliver with or without a running event loop."""

    def test_delivers_without_running_event_loop(self) -> None:
        """Regression: sync callers with no loop used to skip delivery entirely."""
        delivered = threading.Event()
        seen: list[dict[str, Any]] = []

        async def _fake_deliver(notification: dict[str, Any]) -> None:
            seen.append(notification)
            delivered.set()

        notification = _make_notification(severity="critical")
        with (
            patch("app.services._agent_hub_config.AGENT_HUB_URL", "http://agent-hub.test"),
            patch("app.services.notifications.delivery.deliver", _fake_deliver),
        ):
            notification_storage._schedule_delivery(notification)
            assert delivered.wait(timeout=5)
        assert seen == [notification]

    def test_skips_low_severity_without_spawning_thread(self) -> None:
        with (
            patch("app.services._agent_hub_config.AGENT_HUB_URL", "http://agent-hub.test"),
            patch.object(notification_storage.threading, "Thread") as thread_cls,
        ):
            notification_storage._schedule_delivery(_make_notification(severity="info"))
        thread_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_running_loop_schedules_task_without_thread(self) -> None:
        fake_deliver = AsyncMock()
        with (
            patch("app.services._agent_hub_config.AGENT_HUB_URL", "http://agent-hub.test"),
            patch("app.services.notifications.delivery.deliver", fake_deliver),
            patch.object(notification_storage.threading, "Thread") as thread_cls,
        ):
            notification_storage._schedule_delivery(_make_notification(severity="error"))
            await asyncio.gather(*notification_storage._background_tasks)
        thread_cls.assert_not_called()
        fake_deliver.assert_awaited_once()
