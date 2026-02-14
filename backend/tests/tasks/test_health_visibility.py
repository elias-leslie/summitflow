"""Tests for agent health visibility during execution.

Covers:
- check_system_health() in pickup_guards.py
- _check_health_or_wait() in execution_loop.py
- build_health_context() in prompts.py
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from app.tasks.autonomous.exec_modules.execution_loop import _check_health_or_wait
from app.tasks.autonomous.exec_modules.prompts import build_health_context
from app.tasks.autonomous.pickup_guards import check_system_health


class TestCheckSystemHealth:
    """Tests for check_system_health() health check function."""

    @patch("app.tasks.autonomous.pickup_guards.get_connection")
    @patch("redis.Redis.from_url")
    @patch("app.tasks.autonomous.pickup_guards.subprocess.run")
    def test_returns_none_when_all_services_healthy(
        self,
        mock_subprocess: MagicMock,
        mock_redis: MagicMock,
        mock_get_conn: MagicMock,
    ) -> None:
        """Test check_system_health returns None when all services are healthy."""
        # Arrange - all services healthy
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)
        mock_get_conn.return_value = mock_conn

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_subprocess.return_value = MagicMock(stdout="active\n")

        # Act
        result = check_system_health("test-project")

        # Assert
        assert result is None
        mock_cursor.execute.assert_called_once_with("SELECT 1")
        mock_redis_client.ping.assert_called_once()

    @patch("app.tasks.autonomous.pickup_guards.get_connection")
    @patch("redis.Redis.from_url")
    @patch("app.tasks.autonomous.pickup_guards.subprocess.run")
    def test_returns_error_dict_when_postgres_down(
        self,
        mock_subprocess: MagicMock,
        mock_redis: MagicMock,
        mock_get_conn: MagicMock,
    ) -> None:
        """Test check_system_health returns error dict with status unhealthy when postgres is down."""
        # Arrange - postgres fails
        mock_get_conn.side_effect = Exception("Connection refused")

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_subprocess.return_value = MagicMock(stdout="active\n")

        # Act
        result = check_system_health("test-project")

        # Assert
        assert result is not None
        assert result["status"] == "unhealthy"
        assert "postgres" in result["failing_services"]
        assert "postgres" in result["details"]
        assert "Connection refused" in result["details"]["postgres"]

    @patch("app.tasks.autonomous.pickup_guards.get_connection")
    @patch("redis.Redis.from_url")
    @patch("app.tasks.autonomous.pickup_guards.subprocess.run")
    def test_returns_error_dict_when_redis_down(
        self,
        mock_subprocess: MagicMock,
        mock_redis: MagicMock,
        mock_get_conn: MagicMock,
    ) -> None:
        """Test check_system_health returns error dict with failing_services when redis is down."""
        # Arrange - redis fails
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)
        mock_get_conn.return_value = mock_conn

        mock_redis.side_effect = Exception("Connection timeout")

        mock_subprocess.return_value = MagicMock(stdout="active\n")

        # Act
        result = check_system_health("test-project")

        # Assert
        assert result is not None
        assert result["status"] == "unhealthy"
        assert "redis" in result["failing_services"]
        assert "redis" in result["details"]
        assert "Connection timeout" in result["details"]["redis"]

    @patch("app.tasks.autonomous.pickup_guards.get_connection")
    @patch("redis.Redis.from_url")
    @patch("app.tasks.autonomous.pickup_guards.subprocess.run")
    def test_returns_error_dict_when_backend_inactive(
        self,
        mock_subprocess: MagicMock,
        mock_redis: MagicMock,
        mock_get_conn: MagicMock,
    ) -> None:
        """Test check_system_health returns error dict when backend service is inactive."""
        # Arrange - backend inactive
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)
        mock_get_conn.return_value = mock_conn

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_subprocess.return_value = MagicMock(stdout="inactive\n")

        # Act
        result = check_system_health("test-project")

        # Assert
        assert result is not None
        assert result["status"] == "unhealthy"
        assert "backend" in result["failing_services"]
        assert "backend" in result["details"]
        assert "inactive" in result["details"]["backend"]

    @patch("app.tasks.autonomous.pickup_guards.get_connection")
    @patch("redis.Redis.from_url")
    @patch("app.tasks.autonomous.pickup_guards.subprocess.run")
    def test_returns_error_dict_with_multiple_failing_services(
        self,
        mock_subprocess: MagicMock,
        mock_redis: MagicMock,
        mock_get_conn: MagicMock,
    ) -> None:
        """Test check_system_health aggregates multiple service failures."""
        # Arrange - postgres and redis both fail
        mock_get_conn.side_effect = Exception("postgres down")
        mock_redis.side_effect = Exception("redis down")
        mock_subprocess.return_value = MagicMock(stdout="active\n")

        # Act
        result = check_system_health("test-project")

        # Assert
        assert result is not None
        assert result["status"] == "unhealthy"
        assert len(result["failing_services"]) == 2
        assert "postgres" in result["failing_services"]
        assert "redis" in result["failing_services"]

    @patch("app.tasks.autonomous.pickup_guards.get_connection")
    @patch("redis.Redis.from_url")
    @patch("app.tasks.autonomous.pickup_guards.subprocess.run")
    def test_backend_check_unavailable_does_not_block(
        self,
        mock_subprocess: MagicMock,
        mock_redis: MagicMock,
        mock_get_conn: MagicMock,
    ) -> None:
        """Test check_system_health does not block dispatch when backend check fails."""
        # Arrange - backend check throws exception
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)
        mock_get_conn.return_value = mock_conn

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_subprocess.side_effect = Exception("systemctl unavailable")

        # Act
        result = check_system_health("test-project")

        # Assert - should return None (not blocked) even though backend check failed
        assert result is None


class TestCheckHealthOrWait:
    """Tests for _check_health_or_wait() with exponential backoff."""

    @patch("app.tasks.autonomous.exec_modules.execution_loop.check_system_health")
    @patch("app.tasks.autonomous.exec_modules.execution_loop.emit_log")
    def test_returns_true_immediately_when_healthy(
        self,
        mock_emit_log: MagicMock,
        mock_check_health: MagicMock,
    ) -> None:
        """Test _check_health_or_wait returns True immediately when system is healthy."""
        # Arrange
        mock_check_health.return_value = None

        # Act
        result = _check_health_or_wait("task-123", "test-project", max_retries=3)

        # Assert
        assert result is True
        mock_check_health.assert_called_once_with("test-project")
        mock_emit_log.assert_not_called()

    @patch("app.tasks.autonomous.exec_modules.execution_loop.check_system_health")
    @patch("app.tasks.autonomous.exec_modules.execution_loop.emit_log")
    @patch("app.tasks.autonomous.exec_modules.execution_loop.time.sleep")
    def test_retries_with_backoff_when_unhealthy(
        self,
        mock_sleep: MagicMock,
        mock_emit_log: MagicMock,
        mock_check_health: MagicMock,
    ) -> None:
        """Test _check_health_or_wait retries with exponential backoff when unhealthy."""
        # Arrange - unhealthy on first check, healthy on second
        mock_check_health.side_effect = [
            {"status": "unhealthy", "failing_services": ["redis"]},
            None,
        ]

        # Act
        result = _check_health_or_wait("task-123", "test-project", max_retries=3)

        # Assert
        assert result is True
        assert mock_check_health.call_count == 2
        mock_sleep.assert_called_once_with(30)
        assert mock_emit_log.call_count == 2
        warn_call = mock_emit_log.call_args_list[0]
        assert warn_call[0][1] == "warn"
        assert "redis" in warn_call[0][2]
        assert "waiting 30s" in warn_call[0][2]
        info_call = mock_emit_log.call_args_list[1]
        assert info_call[0][1] == "info"
        assert "recovered" in info_call[0][2]

    @patch("app.tasks.autonomous.exec_modules.execution_loop.check_system_health")
    @patch("app.tasks.autonomous.exec_modules.execution_loop.emit_log")
    @patch("app.tasks.autonomous.exec_modules.execution_loop.time.sleep")
    def test_returns_false_after_max_retries_exhausted(
        self,
        mock_sleep: MagicMock,
        mock_emit_log: MagicMock,
        mock_check_health: MagicMock,
    ) -> None:
        """Test _check_health_or_wait returns False after max_retries exhausted."""
        # Arrange - always unhealthy
        mock_check_health.return_value = {
            "status": "unhealthy",
            "failing_services": ["postgres"],
        }

        # Act
        result = _check_health_or_wait("task-123", "test-project", max_retries=3)

        # Assert
        assert result is False
        assert mock_check_health.call_count == 4  # initial + 3 retries
        assert mock_sleep.call_count == 3
        mock_sleep.assert_any_call(30)
        mock_sleep.assert_any_call(60)
        mock_sleep.assert_any_call(120)

    @patch("app.tasks.autonomous.exec_modules.execution_loop.check_system_health")
    @patch("app.tasks.autonomous.exec_modules.execution_loop.emit_log")
    @patch("app.tasks.autonomous.exec_modules.execution_loop.time.sleep")
    def test_uses_exponential_backoff_delays(
        self,
        mock_sleep: MagicMock,
        mock_emit_log: MagicMock,
        mock_check_health: MagicMock,
    ) -> None:
        """Test _check_health_or_wait uses correct exponential backoff delays."""
        # Arrange - unhealthy for first 3 checks, then healthy
        mock_check_health.side_effect = [
            {"status": "unhealthy", "failing_services": ["redis"]},
            {"status": "unhealthy", "failing_services": ["redis"]},
            {"status": "unhealthy", "failing_services": ["redis"]},
            None,
        ]

        # Act
        result = _check_health_or_wait("task-123", "test-project", max_retries=3)

        # Assert
        assert result is True
        assert mock_sleep.call_count == 3
        assert mock_sleep.call_args_list[0][0][0] == 30
        assert mock_sleep.call_args_list[1][0][0] == 60
        assert mock_sleep.call_args_list[2][0][0] == 120

    @patch("app.tasks.autonomous.exec_modules.execution_loop.check_system_health")
    @patch("app.tasks.autonomous.exec_modules.execution_loop.emit_log")
    @patch("app.tasks.autonomous.exec_modules.execution_loop.time.sleep")
    def test_caps_delay_at_max_backoff(
        self,
        mock_sleep: MagicMock,
        mock_emit_log: MagicMock,
        mock_check_health: MagicMock,
    ) -> None:
        """Test _check_health_or_wait caps delay at maximum backoff value."""
        # Arrange - unhealthy for many retries
        mock_check_health.return_value = {
            "status": "unhealthy",
            "failing_services": ["redis"],
        }

        # Act
        result = _check_health_or_wait("task-123", "test-project", max_retries=5)

        # Assert
        assert result is False
        assert mock_sleep.call_count == 5
        assert mock_sleep.call_args_list[0][0][0] == 30
        assert mock_sleep.call_args_list[1][0][0] == 60
        assert mock_sleep.call_args_list[2][0][0] == 120
        assert mock_sleep.call_args_list[3][0][0] == 120
        assert mock_sleep.call_args_list[4][0][0] == 120

    @patch("app.tasks.autonomous.exec_modules.execution_loop.check_system_health")
    @patch("app.tasks.autonomous.exec_modules.execution_loop.emit_log")
    @patch("app.tasks.autonomous.exec_modules.execution_loop.time.sleep")
    def test_logs_failing_services_in_warning(
        self,
        mock_sleep: MagicMock,
        mock_emit_log: MagicMock,
        mock_check_health: MagicMock,
    ) -> None:
        """Test _check_health_or_wait logs specific failing services in warning."""
        # Arrange
        mock_check_health.side_effect = [
            {
                "status": "unhealthy",
                "failing_services": ["postgres", "redis"],
                "details": {},
            },
            None,
        ]

        # Act
        result = _check_health_or_wait("task-123", "test-project", max_retries=3)

        # Assert
        assert result is True
        warn_call = mock_emit_log.call_args_list[0]
        assert "postgres, redis" in warn_call[0][2]
        assert warn_call[1]["source"] == "health"


class TestBuildHealthContext:
    """Tests for build_health_context() prompt injection."""

    @patch("app.tasks.autonomous.exec_modules.prompts.check_system_health")
    def test_returns_empty_string_when_all_services_healthy(
        self,
        mock_check_health: MagicMock,
    ) -> None:
        """Test build_health_context returns empty string when all services are healthy."""
        # Arrange
        mock_check_health.return_value = None

        # Act
        result = build_health_context("test-project")

        # Assert
        assert result == ""
        mock_check_health.assert_called_once_with("test-project")

    @patch("app.tasks.autonomous.exec_modules.prompts.check_system_health")
    def test_returns_markdown_health_summary_when_services_degraded(
        self,
        mock_check_health: MagicMock,
    ) -> None:
        """Test build_health_context returns markdown health summary when services are degraded."""
        # Arrange
        mock_check_health.return_value = {
            "status": "unhealthy",
            "failing_services": ["redis"],
            "details": {
                "postgres": "healthy",
                "redis": "unhealthy: Connection refused",
                "backend": "healthy",
            },
        }

        # Act
        result = build_health_context("test-project")

        # Assert
        assert result != ""
        assert "## System Health Warning" in result
        assert "postgres: healthy" in result
        assert "redis: unhealthy" in result
        assert "backend: healthy" in result
        assert "Some services are degraded" in result

    @patch("app.tasks.autonomous.exec_modules.prompts.check_system_health")
    def test_returns_empty_string_when_check_throws_exception(
        self,
        mock_check_health: MagicMock,
    ) -> None:
        """Test build_health_context returns empty string when health check throws exception."""
        # Arrange
        mock_check_health.side_effect = Exception("Health check failed")

        # Act
        result = build_health_context("test-project")

        # Assert
        assert result == ""

    @patch("app.tasks.autonomous.exec_modules.prompts.check_system_health")
    def test_formats_multiple_services_correctly(
        self,
        mock_check_health: MagicMock,
    ) -> None:
        """Test build_health_context formats multiple services with correct status indicators."""
        # Arrange
        mock_check_health.return_value = {
            "status": "unhealthy",
            "failing_services": ["postgres", "backend"],
            "details": {
                "postgres": "unhealthy: Connection timeout",
                "redis": "healthy",
                "backend": "unhealthy: inactive",
            },
        }

        # Act
        result = build_health_context("test-project")

        # Assert
        assert "postgres: unhealthy" in result
        assert "redis: healthy" in result
        assert "backend: unhealthy" in result
        lines = result.split("\n")
        assert any("postgres: unhealthy" in line for line in lines)
        assert any("redis: healthy" in line for line in lines)
        assert any("backend: unhealthy" in line for line in lines)

    @patch("app.tasks.autonomous.exec_modules.prompts.check_system_health")
    def test_handles_missing_details_gracefully(
        self,
        mock_check_health: MagicMock,
    ) -> None:
        """Test build_health_context handles missing details field gracefully."""
        # Arrange - error dict without details field
        mock_check_health.return_value = {
            "status": "unhealthy",
            "failing_services": ["redis"],
        }

        # Act
        result = build_health_context("test-project")

        # Assert
        assert result != ""
        assert "## System Health Warning" in result

    @patch("app.tasks.autonomous.exec_modules.prompts.check_system_health")
    def test_includes_guidance_to_avoid_unhealthy_services(
        self,
        mock_check_health: MagicMock,
    ) -> None:
        """Test build_health_context includes guidance for agents to avoid unhealthy services."""
        # Arrange
        mock_check_health.return_value = {
            "status": "unhealthy",
            "failing_services": ["redis"],
            "details": {
                "postgres": "healthy",
                "redis": "unhealthy: timeout",
                "backend": "healthy",
            },
        }

        # Act
        result = build_health_context("test-project")

        # Assert
        assert "Avoid operations that depend on unhealthy services" in result
