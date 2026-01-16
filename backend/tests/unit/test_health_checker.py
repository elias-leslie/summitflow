"""Unit tests for MemoryHealthChecker."""

import time
from unittest.mock import patch


class TestGetHealthMetrics:
    """Tests for get_health_metrics method."""

    @patch("app.services.memory.pattern_applier.memory_storage")
    @patch("app.services.memory.health_checker.get_embedding_coverage")
    @patch("app.services.memory.health_checker.get_pattern_status_breakdown")
    @patch("app.services.memory.health_checker.get_observation_distribution")
    def test_returns_expected_structure(
        self, mock_obs_dist, mock_pattern_status, mock_embed_cov, mock_storage
    ):
        """Health metrics dict has expected keys."""
        from app.services.memory.health_checker import MemoryHealthChecker

        # Mock DB function return values
        mock_obs_dist.return_value = {"refactoring": 5, "operational": 3}
        mock_pattern_status.return_value = {"approved": 2, "applied": 1}
        mock_embed_cov.return_value = {"total": 10, "with_embeddings": 8}

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
    @patch("app.services.memory.health_checker.get_embedding_coverage")
    @patch("app.services.memory.health_checker.get_pattern_status_breakdown")
    @patch("app.services.memory.health_checker.get_observation_distribution")
    def test_applies_approved_patterns(
        self, mock_obs_dist, mock_pattern_status, mock_embed_cov, mock_storage
    ):
        """Applies approved patterns and records correction."""
        from app.services.memory.health_checker import MemoryHealthChecker

        # Mock approved patterns
        mock_storage.list_patterns.return_value = [
            {"id": "pat-1", "title": "Test Pattern", "confidence": 0.8},
        ]

        # Mock DB function return values
        mock_obs_dist.return_value = {}
        mock_pattern_status.return_value = {"approved": 1}
        mock_embed_cov.return_value = {"total": 0, "with_embeddings": 0}

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
