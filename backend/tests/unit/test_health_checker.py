"""Unit tests for MemoryHealthChecker."""

import time
from unittest.mock import MagicMock, patch


class TestGetHealthMetrics:
    """Tests for get_health_metrics method."""

    @patch("app.services.memory.pattern_applier.memory_storage")
    @patch("app.services.memory.health_checker.get_connection")
    def test_returns_expected_structure(self, mock_get_conn, mock_storage):
        """Health metrics dict has expected keys."""
        from app.services.memory.health_checker import MemoryHealthChecker

        # Mock DB calls
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("refactoring", 5), ("operational", 3)]
        mock_cursor.fetchone.return_value = (10, 8)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

        # Mock storage
        mock_storage.list_patterns.return_value = []

        checker = MemoryHealthChecker(project_id="test-project")

        with patch(
            "app.services.memory.health_checker.MemoryHealthChecker._get_filter_stats"
        ) as mock_filter:
            mock_filter.return_value = {"tools_received": 100, "skip_rate": 0.3}
            metrics = checker.get_health_metrics()

        assert "filter_stats" in metrics
        assert "observation_distribution" in metrics
        assert "pattern_status" in metrics
        assert "embedding_coverage" in metrics
        assert "approved_patterns_waiting" in metrics

    def test_raises_without_project_id(self):
        """Raises ValueError when no project_id provided."""
        import pytest
        from app.services.memory.health_checker import MemoryHealthChecker

        checker = MemoryHealthChecker()  # No project_id

        with pytest.raises(ValueError, match="project_id required"):
            checker.get_health_metrics()


class TestCheckAndCorrect:
    """Tests for check_and_correct method."""

    @patch("app.services.memory.pattern_applier.memory_storage")
    @patch("app.services.memory.health_checker.get_connection")
    def test_applies_approved_patterns(self, mock_get_conn, mock_storage):
        """Applies approved patterns and records correction."""
        from app.services.memory.health_checker import MemoryHealthChecker

        # Mock approved patterns
        mock_storage.list_patterns.return_value = [
            {"id": "pat-1", "title": "Test Pattern", "confidence": 0.8},
        ]

        # Mock DB calls
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = (0, 0)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

        checker = MemoryHealthChecker(project_id="summitflow")

        with patch(
            "app.services.memory.health_checker.MemoryHealthChecker._get_filter_stats"
        ) as mock_filter:
            mock_filter.return_value = {"tools_received": 100, "skip_rate": 0.1}
            with patch(
                "app.services.memory.health_checker.MemoryHealthChecker._apply_approved_patterns"
            ) as mock_apply:
                mock_apply.return_value = 1
                report = checker.check_and_correct()

        # Should have called apply with the approved patterns
        mock_apply.assert_called_once()
        # Check report has correction
        assert len(report.corrections) > 0
        assert report.corrections[0].correction_type == "auto_applied_patterns"


class TestQuickCheck:
    """Tests for quick_check method - must be fast (<100ms)."""

    @patch("app.services.memory.pattern_applier.memory_storage")
    def test_completes_under_100ms(self, mock_storage):
        """Quick check completes in under 100ms."""
        from app.services.memory.health_checker import MemoryHealthChecker

        mock_storage.list_patterns.return_value = []

        checker = MemoryHealthChecker(project_id="test-project")

        start = time.time()
        result = checker.quick_check()
        elapsed_ms = (time.time() - start) * 1000

        assert result is True
        assert elapsed_ms < 100, f"quick_check took {elapsed_ms:.1f}ms, expected <100ms"

    def test_returns_false_without_project_id(self):
        """Returns False when no project_id provided."""
        from app.services.memory.health_checker import MemoryHealthChecker

        checker = MemoryHealthChecker()  # No project_id
        result = checker.quick_check()
        assert result is False


class TestApplyPatternsUsesRootPath:
    """Tests that apply_approved_patterns uses root_path column."""

    @patch("app.services.memory.pattern_service.PatternService")
    @patch("app.storage.connection.get_connection")
    def test_queries_root_path_not_local_path(self, mock_get_conn, mock_service_class):
        """Database query uses root_path column for project lookup."""
        from app.services.memory.pattern_applier import apply_approved_patterns

        # Setup mock to capture the SQL query
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("/home/user/myproject",)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

        # Setup PatternService mock
        mock_service = MagicMock()
        mock_service.apply_pattern.return_value = True
        mock_service_class.return_value = mock_service

        patterns = [{"id": "pat-1", "title": "Test", "confidence": 0.8}]

        apply_approved_patterns("portfolio-ai", patterns)

        # Check the query used root_path
        call_args = mock_cursor.execute.call_args
        assert call_args is not None, "execute was not called"
        sql = call_args[0][0]
        assert "root_path" in sql, f"Query should use root_path: {sql}"
        assert "local_path" not in sql, f"Query should NOT use local_path: {sql}"
