"""Unit tests for memory lifecycle cleanup functions."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app.storage.memory import (
    _compute_observation_hash,
    archive_failed_queue_items,
    cleanup_old_checkpoints,
    create_observation,
    get_lifecycle_stats,
    reset_stuck_queue_items,
)


class TestGetLifecycleStats:
    """Tests for get_lifecycle_stats function."""

    def test_returns_expected_shape(self) -> None:
        """Test that get_lifecycle_stats returns dict with expected keys."""
        stats = get_lifecycle_stats()

        assert "failed_queue_count" in stats
        assert "stuck_queue_count" in stats
        assert "oldest_pending_age_minutes" in stats
        assert "unreflected_diary_count" in stats
        assert "stale_patterns_count" in stats
        assert "pattern_status_breakdown" in stats

        assert isinstance(stats["failed_queue_count"], int)
        assert isinstance(stats["stuck_queue_count"], int)
        assert isinstance(stats["unreflected_diary_count"], int)
        assert isinstance(stats["stale_patterns_count"], int)
        assert isinstance(stats["pattern_status_breakdown"], dict)

    def test_supports_project_filter(self) -> None:
        """Test that project_id filter is accepted."""
        stats = get_lifecycle_stats(project_id="summitflow")
        assert isinstance(stats, dict)


class TestCleanupFunctions:
    """Tests for cleanup storage functions."""

    def test_archive_failed_queue_items_returns_int(self) -> None:
        """Test archive_failed_queue_items returns deleted count."""
        result = archive_failed_queue_items(max_age_days=14)
        assert isinstance(result, int)
        assert result >= 0

    def test_cleanup_old_checkpoints_returns_int(self) -> None:
        """Test cleanup_old_checkpoints returns deleted count."""
        result = cleanup_old_checkpoints(max_age_days=30)
        assert isinstance(result, int)
        assert result >= 0

    def test_reset_stuck_queue_items_returns_int(self) -> None:
        """Test reset_stuck_queue_items returns reset count."""
        result = reset_stuck_queue_items(threshold_minutes=60)
        assert isinstance(result, int)
        assert result >= 0


class TestObservationDeduplication:
    """Tests for observation deduplication logic."""

    def test_compute_observation_hash_consistent(self) -> None:
        """Test hash function produces consistent results."""
        hash1 = _compute_observation_hash("Test Title", "error", "Bash")
        hash2 = _compute_observation_hash("Test Title", "error", "Bash")
        assert hash1 == hash2
        assert len(hash1) == 16  # SHA256 truncated to 16 chars

    def test_compute_observation_hash_different_for_different_inputs(self) -> None:
        """Test hash function produces different results for different inputs."""
        hash1 = _compute_observation_hash("Title A", "error", "Bash")
        hash2 = _compute_observation_hash("Title B", "error", "Bash")
        hash3 = _compute_observation_hash("Title A", "decision", "Bash")
        hash4 = _compute_observation_hash("Title A", "error", "Read")

        assert hash1 != hash2
        assert hash1 != hash3
        assert hash1 != hash4

    def test_create_observation_skips_duplicate(self) -> None:
        """Test that duplicate observations in same session are skipped."""
        session_id = str(uuid.uuid4())

        # First observation should succeed
        result1 = create_observation(
            project_id="summitflow",
            session_id=session_id,
            agent_type="test",
            observation_type="test_dedup",
            title="Duplicate Test",
            tool_name="TestTool",
            skip_memory_check=True,
        )
        assert result1 is not None
        assert "id" in result1

        # Second identical observation should be skipped
        result2 = create_observation(
            project_id="summitflow",
            session_id=session_id,
            agent_type="test",
            observation_type="test_dedup",
            title="Duplicate Test",
            tool_name="TestTool",
            skip_memory_check=True,
        )
        assert result2 is None  # Duplicate was skipped

    def test_create_observation_allows_different_title(self) -> None:
        """Test that different titles create separate observations."""
        session_id = str(uuid.uuid4())

        result1 = create_observation(
            project_id="summitflow",
            session_id=session_id,
            agent_type="test",
            observation_type="test_dedup",
            title="Title One",
            tool_name="TestTool",
            skip_memory_check=True,
        )
        assert result1 is not None

        result2 = create_observation(
            project_id="summitflow",
            session_id=session_id,
            agent_type="test",
            observation_type="test_dedup",
            title="Title Two",
            tool_name="TestTool",
            skip_memory_check=True,
        )
        assert result2 is not None
        assert result1["id"] != result2["id"]

    def test_create_observation_allows_different_session(self) -> None:
        """Test that same observation in different sessions is allowed."""
        result1 = create_observation(
            project_id="summitflow",
            session_id=str(uuid.uuid4()),
            agent_type="test",
            observation_type="test_dedup",
            title="Same Title",
            tool_name="TestTool",
            skip_memory_check=True,
        )
        assert result1 is not None

        result2 = create_observation(
            project_id="summitflow",
            session_id=str(uuid.uuid4()),
            agent_type="test",
            observation_type="test_dedup",
            title="Same Title",
            tool_name="TestTool",
            skip_memory_check=True,
        )
        assert result2 is not None
        assert result1["id"] != result2["id"]


class TestPatternLifecycleCleanup:
    """Tests for pattern lifecycle cleanup functions."""

    @patch("app.storage.memory_patterns.get_connection")
    def test_cleanup_low_relevance_patterns_deletes_old_low_conf(self, mock_get_conn):
        """Deletes patterns with low confidence older than threshold."""
        from datetime import datetime

        from app.storage.memory_patterns import cleanup_low_relevance_patterns

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("pat-1", "project-a", "Old Pattern", 0.2, datetime(2025, 1, 1)),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        result = cleanup_low_relevance_patterns(min_relevance=0.3, min_age_days=30)

        assert len(result) == 1
        assert result[0]["id"] == "pat-1"
        assert result[0]["title"] == "Old Pattern"
        mock_conn.commit.assert_called_once()

    @patch("app.storage.memory_patterns.get_connection")
    def test_cleanup_low_relevance_patterns_no_matches(self, mock_get_conn):
        """Returns empty list when no patterns match criteria."""
        from app.storage.memory_patterns import cleanup_low_relevance_patterns

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        result = cleanup_low_relevance_patterns()

        assert result == []
        mock_conn.commit.assert_not_called()

    @patch("app.storage.memory_patterns.get_connection")
    def test_enforce_pattern_cap_deletes_excess(self, mock_get_conn):
        """Deletes lowest-ranked patterns when over cap."""
        from datetime import datetime

        from app.storage.memory_patterns import enforce_pattern_cap

        mock_cursor = MagicMock()
        # First call: count returns 52
        # Second call: returns 2 patterns to delete
        mock_cursor.fetchone.return_value = (52,)
        mock_cursor.fetchall.return_value = [
            ("pat-low-1", "Low Pattern 1", 0.1, 0, None),
            ("pat-low-2", "Low Pattern 2", 0.2, 1, datetime(2025, 11, 1)),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        result = enforce_pattern_cap("test-project", max_patterns=50)

        assert len(result) == 2
        assert result[0]["id"] == "pat-low-1"
        assert result[1]["id"] == "pat-low-2"
        mock_conn.commit.assert_called_once()

    @patch("app.storage.memory_patterns.get_connection")
    def test_enforce_pattern_cap_under_limit(self, mock_get_conn):
        """Does nothing when pattern count is under cap."""
        from app.storage.memory_patterns import enforce_pattern_cap

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (30,)  # Under limit
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        result = enforce_pattern_cap("test-project", max_patterns=50)

        assert result == []
        mock_conn.commit.assert_not_called()


class TestHealthTaskLifecycleIntegration:
    """Tests for lifecycle integration in health checker."""

    @patch("app.services.memory.health_checker.enforce_pattern_cap")
    @patch("app.services.memory.health_checker.cleanup_low_relevance_patterns")
    def test_run_pattern_lifecycle_calls_cleanup(self, mock_cleanup, mock_cap):
        """Verifies lifecycle functions are called during health check."""
        from app.services.memory.health_checker import MemoryHealthChecker
        from app.services.memory.types import HealthReport

        mock_cleanup.return_value = []
        mock_cap.return_value = []

        checker = MemoryHealthChecker(project_id="test")
        report = HealthReport()
        checker._run_pattern_lifecycle("test", report)

        mock_cleanup.assert_called_once_with(min_relevance=0.3, min_age_days=30)
        mock_cap.assert_called_once_with("test", max_patterns=50)

    @patch("app.services.memory.health_checker.enforce_pattern_cap")
    @patch("app.services.memory.health_checker.cleanup_low_relevance_patterns")
    def test_lifecycle_adds_corrections_when_patterns_deleted(self, mock_cleanup, mock_cap):
        """Corrections added to report when patterns are cleaned/capped."""
        from app.services.memory.health_checker import MemoryHealthChecker
        from app.services.memory.types import HealthReport

        mock_cleanup.return_value = [{"id": "pat-1", "title": "Old Pattern", "confidence": 0.1}]
        mock_cap.return_value = [{"id": "pat-2", "title": "Excess Pattern", "confidence": 0.3}]

        checker = MemoryHealthChecker(project_id="test")
        report = HealthReport()
        checker._run_pattern_lifecycle("test", report)

        # Should have 2 corrections
        assert len(report.corrections) == 2
        assert any(
            c.correction_type == "cleaned_low_relevance_patterns" for c in report.corrections
        )
        assert any(c.correction_type == "enforced_pattern_cap" for c in report.corrections)
