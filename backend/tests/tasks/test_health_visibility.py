"""Tests for system health checks.

Covers check_system_health() in pickup_guards.py."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from app.tasks.autonomous.pickup_guards import check_system_health


class TestCheckSystemHealth:
    """Tests for check_system_health() health check function."""

    @patch("app.tasks.autonomous.pickup_guards.get_cursor")
    @patch("redis.Redis.from_url")
    @patch("httpx.get")
    def test_returns_none_when_all_services_healthy(
        self,
        mock_httpx_get: MagicMock,
        mock_redis: MagicMock,
        mock_get_conn: MagicMock,
    ) -> None:
        """Test check_system_health returns None when all services are healthy."""
        # Arrange - all services healthy
        mock_cursor = MagicMock()
        mock_get_conn.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_get_conn.return_value.__exit__ = Mock(return_value=None)

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_httpx_get.return_value = MagicMock(status_code=200)

        # Act
        result = check_system_health("test-project")

        # Assert
        assert result is None
        mock_cursor.execute.assert_called_once_with("SELECT 1")
        mock_redis_client.ping.assert_called_once()

    @patch("app.tasks.autonomous.pickup_guards.get_cursor")
    @patch("redis.Redis.from_url")
    @patch("httpx.get")
    def test_returns_error_dict_when_postgres_down(
        self,
        mock_httpx_get: MagicMock,
        mock_redis: MagicMock,
        mock_get_conn: MagicMock,
    ) -> None:
        """Test check_system_health returns error dict with status unhealthy when postgres is down."""
        # Arrange - postgres fails
        mock_get_conn.side_effect = Exception("Connection refused")

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_httpx_get.return_value = MagicMock(status_code=200)

        # Act
        result = check_system_health("test-project")

        # Assert
        assert result is not None
        assert result["status"] == "unhealthy"
        assert "postgres" in result["failing_services"]
        assert "postgres" in result["details"]
        assert "Connection refused" in result["details"]["postgres"]

    @patch("app.tasks.autonomous.pickup_guards.get_cursor")
    @patch("redis.Redis.from_url")
    @patch("httpx.get")
    def test_returns_error_dict_when_redis_down(
        self,
        mock_httpx_get: MagicMock,
        mock_redis: MagicMock,
        mock_get_conn: MagicMock,
    ) -> None:
        """Test check_system_health returns error dict with failing_services when redis is down."""
        # Arrange - redis fails
        mock_cursor = MagicMock()
        mock_get_conn.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_get_conn.return_value.__exit__ = Mock(return_value=None)

        mock_redis.side_effect = Exception("Connection timeout")

        mock_httpx_get.return_value = MagicMock(status_code=200)

        # Act
        result = check_system_health("test-project")

        # Assert
        assert result is not None
        assert result["status"] == "unhealthy"
        assert "redis" in result["failing_services"]
        assert "redis" in result["details"]
        assert "Connection timeout" in result["details"]["redis"]

    @patch("app.tasks.autonomous.pickup_guards.get_cursor")
    @patch("redis.Redis.from_url")
    @patch("httpx.get")
    def test_returns_error_dict_when_backend_inactive(
        self,
        mock_httpx_get: MagicMock,
        mock_redis: MagicMock,
        mock_get_conn: MagicMock,
    ) -> None:
        """Test check_system_health returns error dict when backend service is inactive."""
        # Arrange - backend inactive
        mock_cursor = MagicMock()
        mock_get_conn.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_get_conn.return_value.__exit__ = Mock(return_value=None)

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_httpx_get.return_value = MagicMock(status_code=503)

        # Act
        result = check_system_health("test-project")

        # Assert
        assert result is not None
        assert result["status"] == "unhealthy"
        assert "backend" in result["failing_services"]
        assert "backend" in result["details"]
        assert "status=503" in result["details"]["backend"]

    @patch("app.tasks.autonomous.pickup_guards.get_cursor")
    @patch("redis.Redis.from_url")
    @patch("httpx.get")
    def test_returns_error_dict_with_multiple_failing_services(
        self,
        mock_httpx_get: MagicMock,
        mock_redis: MagicMock,
        mock_get_conn: MagicMock,
    ) -> None:
        """Test check_system_health aggregates multiple service failures."""
        # Arrange - postgres and redis both fail
        mock_get_conn.side_effect = Exception("postgres down")
        mock_redis.side_effect = Exception("redis down")
        mock_httpx_get.return_value = MagicMock(status_code=200)

        # Act
        result = check_system_health("test-project")

        # Assert
        assert result is not None
        assert result["status"] == "unhealthy"
        assert len(result["failing_services"]) == 2
        assert "postgres" in result["failing_services"]
        assert "redis" in result["failing_services"]

    @patch("app.tasks.autonomous.pickup_guards.get_cursor")
    @patch("redis.Redis.from_url")
    @patch("httpx.get")
    def test_backend_check_unavailable_does_not_block(
        self,
        mock_httpx_get: MagicMock,
        mock_redis: MagicMock,
        mock_get_conn: MagicMock,
    ) -> None:
        """Test check_system_health does not block dispatch when backend check fails."""
        # Arrange - backend check throws exception
        mock_cursor = MagicMock()
        mock_get_conn.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_get_conn.return_value.__exit__ = Mock(return_value=None)

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_httpx_get.side_effect = Exception("connection refused")

        # Act
        result = check_system_health("test-project")

        # Assert - should return None (not blocked) even though backend check failed
        assert result is None
