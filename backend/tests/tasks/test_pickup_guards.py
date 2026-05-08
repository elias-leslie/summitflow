"""Tests for pickup guard conditions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.pickup_guards import (
    check_autonomous_enabled,
    check_system_health,
    get_concurrency_snapshot,
)


def _mock_response(data: dict) -> MagicMock:
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.json.return_value = data
    return resp


class TestCheckAutonomousEnabled:
    """Tests for check_autonomous_enabled permission tier validation."""

    @patch("httpx.get")
    def test_legacy_write_tier_alias_permits_execution(self, mock_get: MagicMock) -> None:
        """Legacy write tier is treated as full during rollout."""
        mock_get.return_value = _mock_response({"allowed": True, "permission_tier": "write"})
        assert check_autonomous_enabled("proj") is None

    @patch("httpx.get")
    def test_sends_auth_headers(self, mock_get: MagicMock) -> None:
        """HTTP call includes X-Client-Id and X-Request-Source headers."""
        mock_get.return_value = _mock_response({"allowed": True, "permission_tier": "full"})
        check_autonomous_enabled("monkey-fight")
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert "X-Request-Source" in headers
        assert headers["X-Request-Source"] == "sf-pipeline"

    @patch("httpx.get")
    def test_auth_headers_include_client_id_when_configured(self, mock_get: MagicMock) -> None:
        """X-Client-Id header is present when SUMMITFLOW_CLIENT_ID is set."""
        mock_get.return_value = _mock_response({"allowed": True, "permission_tier": "full"})
        with patch("app.services._agent_hub_config.SUMMITFLOW_CLIENT_ID", "test-client-123"):
            check_autonomous_enabled("monkey-fight")
        headers = mock_get.call_args.kwargs.get("headers", {})
        assert headers.get("X-Client-Id") == "test-client-123"

    @patch("httpx.get")
    def test_project_id_interpolated_in_url(self, mock_get: MagicMock) -> None:
        """URL contains the project_id for monkey-fight."""
        mock_get.return_value = _mock_response({"allowed": True, "permission_tier": "full"})
        check_autonomous_enabled("monkey-fight")
        url = mock_get.call_args[0][0]
        assert "monkey-fight" in url
        assert "/execution-permission" in url

    @patch("httpx.get")
    def test_allowed_full_tier(self, mock_get: MagicMock) -> None:
        """Full tier permits autonomous execution."""
        mock_get.return_value = _mock_response({"allowed": True, "permission_tier": "full"})
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


def _mock_healthy_infra() -> tuple:
    """Return (mock_get_conn, mock_redis) configured for healthy postgres+redis."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = lambda s, *a: None
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = lambda s, *a: None
    mock_redis_client = MagicMock()
    mock_redis_client.ping.return_value = True
    return mock_conn, mock_redis_client


class TestCheckSystemHealth:
    """Tests for check_system_health backend HTTP check."""

    @patch("app.tasks.autonomous.pickup_guards.get_cursor")
    @patch("redis.Redis.from_url")
    @patch("httpx.get")
    def test_backend_healthy_via_http(
        self, mock_get: MagicMock, mock_redis_from_url: MagicMock, mock_get_conn: MagicMock
    ) -> None:
        """Backend health check uses HTTP instead of systemctl."""
        mock_conn, mock_redis_client = _mock_healthy_infra()
        mock_get_conn.return_value = mock_conn
        mock_redis_from_url.return_value = mock_redis_client

        mock_get.return_value = MagicMock(status_code=200)

        result = check_system_health("proj")
        assert result is None  # all healthy

    @patch("app.tasks.autonomous.pickup_guards.get_cursor")
    @patch("redis.Redis.from_url")
    @patch("httpx.get")
    def test_backend_unhealthy_via_http(
        self, mock_get: MagicMock, mock_redis_from_url: MagicMock, mock_get_conn: MagicMock
    ) -> None:
        """Backend returns non-200 marks as unhealthy."""
        mock_conn, mock_redis_client = _mock_healthy_infra()
        mock_get_conn.return_value = mock_conn
        mock_redis_from_url.return_value = mock_redis_client

        mock_get.return_value = MagicMock(status_code=503)

        result = check_system_health("proj")
        assert result is not None
        assert "backend" in result["failing_services"]

    @patch("app.tasks.autonomous.pickup_guards.get_cursor")
    @patch("redis.Redis.from_url")
    @patch("httpx.get")
    def test_backend_unavailable_does_not_block(
        self, mock_get: MagicMock, mock_redis_from_url: MagicMock, mock_get_conn: MagicMock
    ) -> None:
        """Unreachable health endpoint treated as unknown, not unhealthy."""
        mock_conn, mock_redis_client = _mock_healthy_infra()
        mock_get_conn.return_value = mock_conn
        mock_redis_from_url.return_value = mock_redis_client

        mock_get.side_effect = ConnectionError("refused")

        result = check_system_health("proj")
        assert result is None  # should not block dispatch


class TestConcurrencySnapshot:
    """Tests for project concurrency accounting."""

    @patch("app.tasks.autonomous.pickup_guards.count_active_agent_hub_sessions", return_value=0)
    @patch("app.tasks.autonomous.pickup_guards.task_store.count_running_tasks", return_value=0)
    @patch("app.tasks.autonomous.pickup_guards.agent_configs.get_agent_config", return_value={"autonomous_max_concurrent": 1})
    def test_can_exclude_current_dispatch_task_from_running_count(
        self,
        _mock_config: MagicMock,
        mock_count_running: MagicMock,
        _mock_sessions: MagicMock,
    ) -> None:
        snapshot = get_concurrency_snapshot("agent-hub", exclude_task_id="task-177f0dec")

        mock_count_running.assert_called_once_with("agent-hub", exclude_task_id="task-177f0dec")
        assert snapshot["running_count"] == 0
        assert snapshot["remaining_capacity"] == 1
